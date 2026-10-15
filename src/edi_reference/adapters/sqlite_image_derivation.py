"""Atomic immutable image batches in SQLite, following the API store's WAL pattern.

Uses its own prefixed tables and can share the API database path. Images contain
document data: apply the same protected storage/backup policy as source bytes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from edi_reference.application.document_images import DocumentImage, DocumentImages
from edi_reference.application.image_derivation import ImageDerivation
from edi_reference.domain.lineage import ProcessingRunBinding

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS image_derivation_batches (
 tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, processing_run_id TEXT NOT NULL,
 manifest TEXT NOT NULL,
 PRIMARY KEY (tenant_id, application_id, processing_run_id)
);
CREATE TABLE IF NOT EXISTS image_derivation_pages (
 tenant_id TEXT NOT NULL, application_id TEXT NOT NULL, processing_run_id TEXT NOT NULL,
 ordinal INTEGER NOT NULL CHECK (ordinal >= 0), content BLOB NOT NULL CHECK (length(content) > 0),
 PRIMARY KEY (tenant_id, application_id, processing_run_id, ordinal),
 FOREIGN KEY (tenant_id, application_id, processing_run_id)
 REFERENCES image_derivation_batches (tenant_id, application_id, processing_run_id)
);
CREATE TRIGGER IF NOT EXISTS image_batches_no_update BEFORE UPDATE ON image_derivation_batches
BEGIN SELECT RAISE(ABORT, 'IMAGE_DERIVATION_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS image_batches_no_delete BEFORE DELETE ON image_derivation_batches
BEGIN SELECT RAISE(ABORT, 'IMAGE_DERIVATION_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS image_pages_no_update BEFORE UPDATE ON image_derivation_pages
BEGIN SELECT RAISE(ABORT, 'IMAGE_DERIVATION_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS image_pages_no_delete BEFORE DELETE ON image_derivation_pages
BEGIN SELECT RAISE(ABORT, 'IMAGE_DERIVATION_IMMUTABLE'); END;
"""


def _manifest(derivation: ImageDerivation) -> str:
    binding = asdict(derivation.binding)
    binding["created_at"] = derivation.binding.created_at.isoformat()
    pages = []
    for page in derivation.prepared.pages:
        metadata = {name: value for name, value in asdict(page).items() if name != "content"}
        metadata["observation_id"] = derivation.image_observation_id(page)
        pages.append(metadata)
    return json.dumps({"version": 1, "binding": binding, "source_sha256": derivation.prepared.source_sha256,
                       "total_pages": derivation.prepared.total_pages, "recipe": derivation.prepared.recipe,
                       "pages": pages}, sort_keys=True, separators=(",", ":"))


class SqliteImageDerivationRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self._db.executescript(_SCHEMA)
        self._lock = threading.RLock()

    def close(self) -> None:
        self._db.close()

    def save(self, derivation: ImageDerivation) -> None:
        manifest = _manifest(derivation)
        b = derivation.binding
        key = (b.tenant_id, b.application_id, b.processing_run_id)
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.get(b.processing_run_id, tenant_id=b.tenant_id, application_id=b.application_id)
                if existing is not None:
                    if existing != derivation:
                        raise ValueError("IMAGE_DERIVATION_CONFLICT")
                else:
                    self._db.execute("INSERT INTO image_derivation_batches VALUES (?,?,?,?)", (*key, manifest))
                    self._db.executemany("INSERT INTO image_derivation_pages VALUES (?,?,?,?,?)",
                        [(*key, index, page.content) for index, page in enumerate(derivation.prepared.pages)])
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def get(self, processing_run_id: str, *, tenant_id: str, application_id: str) -> ImageDerivation | None:
        key = (tenant_id, application_id, processing_run_id)
        where = "WHERE tenant_id=? AND application_id=? AND processing_run_id=?"
        with self._lock:
            row = self._db.execute("SELECT manifest FROM image_derivation_batches " + where, key).fetchone()
            if row is None:
                return None
            raw_pages = self._db.execute(
                "SELECT ordinal, content FROM image_derivation_pages " + where + " ORDER BY ordinal", key).fetchall()
        try:
            data = json.loads(row[0])
            if data["version"] != 1 or [r[0] for r in raw_pages] != list(range(len(data["pages"]))):
                raise ValueError("INVALID_MANIFEST")
            raw_binding = data["binding"]
            raw_binding["created_at"] = datetime.fromisoformat(raw_binding["created_at"])
            binding = ProcessingRunBinding(**raw_binding)
            if (binding.tenant_id, binding.application_id, binding.processing_run_id) != key:
                raise ValueError("INVALID_SCOPE")
            pages = tuple(DocumentImage(content=content, **{k: v for k, v in metadata.items()
                                                           if k != "observation_id"})
                          for (_, content), metadata in zip(raw_pages, data["pages"], strict=True))
            result = ImageDerivation(binding, DocumentImages(data["source_sha256"], data["total_pages"],
                                      pages, tuple(tuple(item) for item in data["recipe"])))
            if any(result.image_observation_id(page) != metadata["observation_id"]
                   for page, metadata in zip(pages, data["pages"], strict=True)):
                raise ValueError("INVALID_IMAGE_OBSERVATION")
            return result
        except (ValueError, TypeError, KeyError, IndexError):
            raise ValueError("IMAGE_DERIVATION_CORRUPT") from None
