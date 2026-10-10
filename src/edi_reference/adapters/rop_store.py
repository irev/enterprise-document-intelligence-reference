"""Single-workstation SQLite adapter with immutable results and review revisions."""

import hashlib
import json
import sqlite3
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from edi_reference.application.ingest import detect_media_type
from edi_reference.domain.human_review import HumanReview, ReviewAction, ReviewActionType
from edi_reference.domain.rop import FIELD_LABELS

MAX_FILE_BYTES = 20 * 1024 * 1024


@contextmanager
def workstation_lock(path: Path):
    """One process per workspace, including when different ports are requested."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_upload(content: bytes, declared: str) -> str:
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("FILE_SIZE_INVALID")
    media = detect_media_type(content)
    if media is None or media != declared:
        raise ValueError("FILE_TYPE_INVALID")
    return media


class WorkspaceStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, media TEXT NOT NULL,
                    digest TEXT NOT NULL, content BLOB NOT NULL, created TEXT NOT NULL,
                    stage TEXT NOT NULL, progress INTEGER NOT NULL, result TEXT,
                    parent_id TEXT REFERENCES documents(id));
                CREATE TABLE IF NOT EXISTS pages (
                    document_id TEXT REFERENCES documents(id), number INTEGER, content BLOB NOT NULL,
                    PRIMARY KEY(document_id, number));
                CREATE TABLE IF NOT EXISTS reviews (
                    document_id TEXT REFERENCES documents(id), version INTEGER,
                    actor TEXT NOT NULL, created TEXT NOT NULL, actions TEXT NOT NULL,
                    PRIMARY KEY(document_id, version));
                CREATE TRIGGER IF NOT EXISTS immutable_result BEFORE UPDATE ON documents
                    WHEN OLD.result IS NOT NULL BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RESULT'); END;
                CREATE TRIGGER IF NOT EXISTS no_result_delete BEFORE DELETE ON documents
                    WHEN OLD.result IS NOT NULL BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_RESULT'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_page BEFORE UPDATE ON pages
                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_PAGE'); END;
                CREATE TRIGGER IF NOT EXISTS no_page_delete BEFORE DELETE ON pages
                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_PAGE'); END;
                CREATE TRIGGER IF NOT EXISTS immutable_review BEFORE UPDATE ON reviews
                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_REVIEW'); END;
                CREATE TRIGGER IF NOT EXISTS no_review_delete BEFORE DELETE ON reviews
                    BEGIN SELECT RAISE(ABORT, 'IMMUTABLE_REVIEW'); END;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, name: str, media: str, content: bytes, parent_id: str | None = None) -> str:
        validate_upload(content, media)
        name = name.replace("\\", "/").split("/")[-1]
        if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
            raise ValueError("INVALID_FILENAME")
        identifier = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?, 'QUEUED',0,NULL,?)",
                       (identifier, name, media, hashlib.sha256(content).hexdigest(), content,
                        datetime.now(UTC).isoformat(), parent_id))
        return identifier

    def list(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,name,media,created,stage,progress,parent_id FROM documents ORDER BY created DESC LIMIT 500")]

    def get(self, identifier: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT id,name,media,digest,created,stage,progress,result,parent_id FROM documents WHERE id=?",
                             (identifier,)).fetchone()
            if row is None:
                raise KeyError(identifier)
            result = dict(row)
            result["result"] = json.loads(result["result"]) if result["result"] else None
            result["reviews"] = [dict(r) for r in db.execute(
                "SELECT version,actor,created,actions FROM reviews WHERE document_id=? ORDER BY version", (identifier,))]
            for review in result["reviews"]:
                review["actions"] = json.loads(review["actions"])
            result["review_version"] = len(result["reviews"])
            return result

    def content(self, identifier: str, page: int | None = None) -> tuple[bytes, str]:
        with self.connect() as db:
            if page is None:
                row = db.execute("SELECT content,media FROM documents WHERE id=?", (identifier,)).fetchone()
            else:
                row = db.execute("SELECT content,'image/png' FROM pages WHERE document_id=? AND number=?",
                                 (identifier, page)).fetchone()
            if row is None:
                raise KeyError(identifier)
            return bytes(row[0]), row[1]

    def pages(self, identifier: str, pages: tuple[bytes, ...]) -> None:
        if sum(map(len, pages)) > 100 * 1024 * 1024:
            raise ValueError("PAGE_STORAGE_LIMIT")
        with self.connect() as db:
            db.executemany("INSERT INTO pages VALUES(?,?,?)", [(identifier, n, p) for n, p in enumerate(pages, 1)])

    def progress(self, identifier: str, stage: str, progress: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE documents SET stage=?,progress=? WHERE id=? AND result IS NULL", (stage, progress, identifier))

    def complete(self, identifier: str, result: dict) -> None:
        with self.connect() as db:
            cursor = db.execute("UPDATE documents SET stage='REVIEW_REQUIRED',progress=100,result=? WHERE id=? AND result IS NULL",
                                (json.dumps(result, allow_nan=False), identifier))
            if cursor.rowcount != 1:
                raise ValueError("RESULT_CONFLICT")

    def recover(self) -> None:
        with self.connect() as db:
            db.execute("UPDATE documents SET stage='INTERRUPTED' WHERE result IS NULL AND stage NOT IN ('FAILED','INTERRUPTED')")

    def review(self, identifier: str, expected: int, values: dict, actor: str) -> int:
        if type(expected) is not int or expected < 0 or not isinstance(values, dict) or not values:
            raise ValueError("INVALID_REVIEW")
        if set(values) - set(FIELD_LABELS) or any(not isinstance(v, str) or len(v) > 2000 for v in values.values()):
            raise ValueError("INVALID_REVIEW")
        review = HumanReview(uuid4().hex, expected + 1, identifier, identifier, actor,
                            tuple(ReviewAction(ReviewActionType.CORRECT, name, value) for name, value in values.items()),
                            datetime.now(UTC))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT result FROM documents WHERE id=?", (identifier,)).fetchone()
            if row is None or row[0] is None:
                raise ValueError("RESULT_REQUIRED")
            version = db.execute("SELECT COALESCE(MAX(version),0) FROM reviews WHERE document_id=?", (identifier,)).fetchone()[0]
            if version != expected:
                raise ValueError("REVIEW_CONFLICT")
            db.execute("INSERT INTO reviews VALUES(?,?,?,?,?)", (identifier, review.review_version, actor,
                       review.created_at.isoformat(), json.dumps(values)))
        return review.review_version
