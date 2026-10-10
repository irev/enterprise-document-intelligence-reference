"""Durable SQLite store for the v1 data-plane API (RI-6.0, decision D6).

Standard-library `sqlite3` in WAL mode, one connection guarded by a lock
(single service process). Invariants are enforced by the database:
- `(tenant_id, application_id, idempotency_key)` is unique (RI-1.11);
- result rows can never be updated or deleted (triggers);
- jobs carry a lease so work interrupted by a crash is picked up again.
Document bytes are not stored here; only their SHA-256 and metadata.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS applications (
  application_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  default_profile TEXT NOT NULL,
  allowed_profiles TEXT NOT NULL,
  rate_per_minute INTEGER NOT NULL CHECK (rate_per_minute > 0),
  max_queued INTEGER NOT NULL CHECK (max_queued > 0),
  max_bytes INTEGER NOT NULL CHECK (max_bytes > 0),
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
  key_id TEXT PRIMARY KEY,
  application_id TEXT NOT NULL REFERENCES applications(application_id),
  secret_sha256 TEXT NOT NULL,
  scopes TEXT NOT NULL,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  revoked_at TEXT,
  last_used_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
  document_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  application_id TEXT NOT NULL REFERENCES applications(application_id),
  idempotency_key TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  media_type TEXT NOT NULL,
  byte_length INTEGER NOT NULL,
  filename TEXT,
  external_references TEXT NOT NULL,
  profile TEXT NOT NULL,
  status TEXT NOT NULL,
  status_code TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  latest_result_version INTEGER,
  UNIQUE (tenant_id, application_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS documents_owner ON documents (tenant_id, application_id, created_at);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(document_id),
  status TEXT NOT NULL CHECK (status IN ('QUEUED', 'RUNNING', 'DONE')),
  attempts INTEGER NOT NULL DEFAULT 0,
  lease_until TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_pending ON jobs (status, created_at);
CREATE TABLE IF NOT EXISTS results (
  document_id TEXT NOT NULL REFERENCES documents(document_id),
  result_version INTEGER NOT NULL CHECK (result_version >= 1),
  status TEXT NOT NULL,
  document_type TEXT NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (document_id, result_version)
);
CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
BEGIN SELECT RAISE(ABORT, 'RESULT_IMMUTABLE'); END;
CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
BEGIN SELECT RAISE(ABORT, 'RESULT_IMMUTABLE'); END;
-- Phase B (ADR-0001). No bearer URL, grant or secret is ever stored in these tables.
CREATE TABLE IF NOT EXISTS storage_connections (
  connection_id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  broker_url TEXT NOT NULL,
  origins TEXT NOT NULL,
  allow_private_network INTEGER NOT NULL DEFAULT 0,
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_sources (
  document_id TEXT PRIMARY KEY REFERENCES documents(document_id),
  connection_id TEXT NOT NULL REFERENCES storage_connections(connection_id),
  object_id TEXT NOT NULL,
  version_id TEXT,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS reprocess_requests (
  document_id TEXT NOT NULL REFERENCES documents(document_id),
  idempotency_key TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  created_at TEXT NOT NULL,
  PRIMARY KEY (document_id, idempotency_key)
);
"""

DOCUMENT_COLUMNS = ("document_id", "tenant_id", "application_id", "idempotency_key", "fingerprint", "correlation_id",
                    "sha256", "media_type", "byte_length", "filename", "external_references", "profile", "status",
                    "status_code", "created_at", "updated_at", "latest_result_version")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class Submission:
    document: dict
    replayed: bool


class IdempotencyConflict(ValueError):
    pass


class SqliteApiStore:
    def __init__(self, path: Path, *, clock: Callable[[], str] = _now) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None, timeout=30)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        # Additive migration for stores created before phase B.
        if "profile" not in {row["name"] for row in self._db.execute("PRAGMA table_info(jobs)")}:
            self._db.execute("ALTER TABLE jobs ADD COLUMN profile TEXT")
        self._lock = threading.RLock()
        self._clock = clock

    def close(self) -> None:
        self._db.close()

    def _tx(self):
        store = self

        class Tx:
            def __enter__(self):
                store._lock.acquire()
                store._db.execute("BEGIN IMMEDIATE")
                return store._db

            def __exit__(self, kind, value, tb):
                try:
                    store._db.execute("COMMIT" if kind is None else "ROLLBACK")
                finally:
                    store._lock.release()
                return False

        return Tx()

    def _one(self, sql: str, *args) -> dict | None:
        with self._lock:
            row = self._db.execute(sql, args).fetchone()
        return None if row is None else dict(row)

    def _all(self, sql: str, *args) -> list[dict]:
        with self._lock:
            return [dict(row) for row in self._db.execute(sql, args).fetchall()]

    # ------------------------------------------------------------ applications and keys
    def create_application(self, *, application_id: str, tenant_id: str, name: str, default_profile: str,
                           allowed_profiles: list[str], rate_per_minute: int, max_queued: int, max_bytes: int,
                           created_by: str) -> dict:
        with self._tx() as db:
            db.execute("INSERT INTO applications VALUES (?,?,?,?,?,?,?,?,0,?,?)",
                       (application_id, tenant_id, name, default_profile, json.dumps(allowed_profiles),
                        rate_per_minute, max_queued, max_bytes, self._clock(), created_by))
        return self.application(application_id) or {}

    def application(self, application_id: str) -> dict | None:
        row = self._one("SELECT * FROM applications WHERE application_id = ?", application_id)
        if row:
            row["allowed_profiles"] = json.loads(row["allowed_profiles"])
            row["disabled"] = bool(row["disabled"])
        return row

    def applications(self) -> list[dict]:
        rows = self._all("SELECT * FROM applications ORDER BY application_id")
        for row in rows:
            row["allowed_profiles"] = json.loads(row["allowed_profiles"])
            row["disabled"] = bool(row["disabled"])
            row["keys"] = self._all("SELECT key_id, scopes, created_at, created_by, revoked_at, last_used_at FROM api_keys "
                                    "WHERE application_id = ? ORDER BY created_at", row["application_id"])
            for key in row["keys"]:
                key["scopes"] = json.loads(key["scopes"])
        return rows

    def set_application_profiles(self, application_id: str, allowed: list[str], default: str) -> None:
        if not allowed or default not in allowed:
            raise ValueError("DEFAULT_PROFILE_MUST_BE_ALLOWED")
        with self._tx() as db:
            if db.execute("UPDATE applications SET allowed_profiles = ?, default_profile = ? WHERE application_id = ?",
                          (json.dumps(sorted(set(allowed))), default, application_id)).rowcount != 1:
                raise LookupError("APPLICATION_NOT_FOUND")

    # ------------------------------------------------------------ storage connections
    def create_connection(self, *, connection_id: str, tenant_id: str, broker_url: str, origins: list[str],
                          allow_private_network: bool, created_by: str) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO storage_connections VALUES (?,?,?,?,?,0,?,?)",
                       (connection_id, tenant_id, broker_url, json.dumps(origins), int(allow_private_network),
                        self._clock(), created_by))

    def connection(self, connection_id: str) -> dict | None:
        row = self._one("SELECT * FROM storage_connections WHERE connection_id = ?", connection_id)
        if row:
            row["origins"] = json.loads(row["origins"])
            row["allow_private_network"], row["disabled"] = bool(row["allow_private_network"]), bool(row["disabled"])
        return row

    def connections(self) -> list[dict]:
        return [self.connection(r["connection_id"]) or {} for r in
                self._all("SELECT connection_id FROM storage_connections ORDER BY connection_id")]

    def set_connection_disabled(self, connection_id: str, disabled: bool) -> None:
        with self._tx() as db:
            if db.execute("UPDATE storage_connections SET disabled = ? WHERE connection_id = ?",
                          (int(disabled), connection_id)).rowcount != 1:
                raise LookupError("STORAGE_CONNECTION_NOT_FOUND")

    def source(self, document_id: str) -> dict | None:
        return self._one("SELECT * FROM document_sources WHERE document_id = ?", document_id)

    def mark_fetched(self, document_id: str, *, media_type: str, byte_length: int) -> None:
        now = self._clock()
        with self._tx() as db:
            db.execute("UPDATE document_sources SET fetched_at = ? WHERE document_id = ?", (now, document_id))
            db.execute("UPDATE documents SET media_type = ?, byte_length = ?, updated_at = ? WHERE document_id = ?",
                       (media_type, byte_length, now, document_id))

    # ------------------------------------------------------------ reprocess
    def reprocess(self, document_id: str, *, idempotency_key: str, fingerprint: str, profile: str) -> tuple[str, bool]:
        """Queue a new processing run for an existing document; returns (job_id, replayed)."""
        with self._tx() as db:
            existing = db.execute("SELECT fingerprint, job_id FROM reprocess_requests WHERE document_id = ? "
                                  "AND idempotency_key = ?", (document_id, idempotency_key)).fetchone()
            if existing is not None:
                if existing["fingerprint"] != fingerprint:
                    raise IdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
                return existing["job_id"], True
            if db.execute("SELECT 1 FROM jobs WHERE document_id = ? AND status != 'DONE'", (document_id,)).fetchone():
                raise ValueError("PROCESSING_ALREADY_PENDING")
            now = self._clock()
            # Random, not derived from the fingerprint: the same request under a new key is a new run.
            job_id = "job_" + secrets.token_hex(13).upper()
            db.execute("INSERT INTO jobs (job_id, document_id, status, created_at, updated_at, profile) "
                       "VALUES (?, ?, 'QUEUED', ?, ?, ?)", (job_id, document_id, now, now, profile))
            db.execute("INSERT INTO reprocess_requests VALUES (?,?,?,?,?)",
                       (document_id, idempotency_key, fingerprint, job_id, now))
            db.execute("UPDATE documents SET status = 'ACCEPTED', updated_at = ? WHERE document_id = ?", (now, document_id))
        return job_id, False

    def set_application_disabled(self, application_id: str, disabled: bool) -> None:
        with self._tx() as db:
            if db.execute("UPDATE applications SET disabled = ? WHERE application_id = ?",
                          (int(disabled), application_id)).rowcount != 1:
                raise LookupError("APPLICATION_NOT_FOUND")

    def add_key(self, *, key_id: str, application_id: str, secret_sha256: str, scopes: list[str], created_by: str) -> None:
        with self._tx() as db:
            db.execute("INSERT INTO api_keys (key_id, application_id, secret_sha256, scopes, created_at, created_by) "
                       "VALUES (?,?,?,?,?,?)", (key_id, application_id, secret_sha256, json.dumps(scopes), self._clock(), created_by))

    def key(self, key_id: str) -> dict | None:
        row = self._one("SELECT k.*, a.tenant_id, a.disabled AS application_disabled FROM api_keys k "
                        "JOIN applications a USING (application_id) WHERE key_id = ?", key_id)
        if row:
            row["scopes"] = json.loads(row["scopes"])
        return row

    def revoke_key(self, key_id: str) -> None:
        with self._tx() as db:
            if db.execute("UPDATE api_keys SET revoked_at = ? WHERE key_id = ? AND revoked_at IS NULL",
                          (self._clock(), key_id)).rowcount != 1:
                raise LookupError("KEY_NOT_FOUND")

    def touch_key(self, key_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE api_keys SET last_used_at = ? WHERE key_id = ?", (self._clock(), key_id))

    # ------------------------------------------------------------ documents
    def submit(self, document: dict, source: dict | None = None) -> Submission:
        """Insert document (+ storage reference) + queued job atomically, or return the idempotent original."""
        with self._tx() as db:
            existing = db.execute("SELECT * FROM documents WHERE tenant_id = ? AND application_id = ? AND idempotency_key = ?",
                                  (document["tenant_id"], document["application_id"], document["idempotency_key"])).fetchone()
            if existing is not None:
                if existing["fingerprint"] != document["fingerprint"]:
                    raise IdempotencyConflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
                return Submission(self._document_view(dict(existing)), True)
            now = self._clock()
            row = dict(document, status="ACCEPTED", status_code=None, created_at=now, updated_at=now,
                       latest_result_version=None, external_references=json.dumps(document["external_references"]))
            db.execute(f"INSERT INTO documents ({','.join(DOCUMENT_COLUMNS)}) VALUES ({','.join('?' * len(DOCUMENT_COLUMNS))})",
                       tuple(row[c] for c in DOCUMENT_COLUMNS))
            if source is not None:
                db.execute("INSERT INTO document_sources (document_id, connection_id, object_id, version_id) VALUES (?,?,?,?)",
                           (document["document_id"], source["connection_id"], source["object_id"], source["version_id"]))
            db.execute("INSERT INTO jobs (job_id, document_id, status, created_at, updated_at) VALUES (?,?, 'QUEUED', ?, ?)",
                       ("job_" + document["document_id"][4:], document["document_id"], now, now))
        return Submission(self.document(document["document_id"]) or {}, False)

    def queued_count(self, tenant_id: str, application_id: str) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM jobs j JOIN documents d USING (document_id) "
                        "WHERE j.status != 'DONE' AND d.tenant_id = ? AND d.application_id = ?", tenant_id, application_id)
        return int(row["n"]) if row else 0

    @staticmethod
    def _document_view(row: dict) -> dict:
        row["external_references"] = json.loads(row["external_references"])
        return row

    def document(self, document_id: str) -> dict | None:
        row = self._one("SELECT * FROM documents WHERE document_id = ?", document_id)
        return None if row is None else self._document_view(row)

    def documents(self, tenant_id: str, application_id: str | None, *, status: str | None, created_after: str | None,
                  external_reference: tuple[str, str] | None, limit: int, cursor: str | None) -> list[dict]:
        sql = "SELECT * FROM documents WHERE tenant_id = ?"
        args: list = [tenant_id]
        if application_id is not None:
            sql += " AND application_id = ?"
            args.append(application_id)
        if status:
            sql += " AND status = ?"
            args.append(status)
        if created_after:
            sql += " AND created_at > ?"
            args.append(created_after)
        if external_reference:
            sql += " AND json_extract(external_references, '$.' || json_quote(?)) = ?"
            args.extend(external_reference)
        if cursor:
            sql += " AND (created_at, document_id) < (SELECT created_at, document_id FROM documents WHERE document_id = ?)"
            args.append(cursor)
        sql += " ORDER BY created_at DESC, document_id DESC LIMIT ?"
        args.append(limit)
        return [self._document_view(row) for row in self._all(sql, *args)]

    # ------------------------------------------------------------ jobs
    def claim(self, *, lease_seconds: int) -> dict | None:
        now = self._clock()
        until = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._tx() as db:
            row = db.execute("SELECT job_id, document_id, attempts, profile FROM jobs WHERE status = 'QUEUED' "
                             "OR (status = 'RUNNING' AND lease_until < ?) ORDER BY created_at LIMIT 1", (now,)).fetchone()
            if row is None:
                return None
            db.execute("UPDATE jobs SET status = 'RUNNING', attempts = attempts + 1, lease_until = ?, updated_at = ? "
                       "WHERE job_id = ?", (until, now, row["job_id"]))
            db.execute("UPDATE documents SET status = 'PROCESSING', updated_at = ? WHERE document_id = ?",
                       (now, row["document_id"]))
            return {"job_id": row["job_id"], "document_id": row["document_id"], "attempts": row["attempts"] + 1,
                    "profile": row["profile"]}

    def complete(self, job_id: str, document_id: str, body: dict) -> int:
        """Append the next immutable result version and finish the job, atomically."""
        now = self._clock()
        with self._tx() as db:
            current = db.execute("SELECT COALESCE(MAX(result_version), 0) AS v FROM results WHERE document_id = ?",
                                 (document_id,)).fetchone()["v"]
            version = int(current) + 1
            body = dict(body, result_version=version)
            db.execute("INSERT INTO results VALUES (?,?,?,?,?,?)",
                       (document_id, version, body["status"], body["classification"]["document_type"],
                        json.dumps(body, ensure_ascii=False), now))
            db.execute("UPDATE documents SET status = ?, latest_result_version = ?, updated_at = ? WHERE document_id = ?",
                       (body["status"], version, now, document_id))
            db.execute("UPDATE jobs SET status = 'DONE', lease_until = NULL, updated_at = ? WHERE job_id = ?", (now, job_id))
        return version

    def results(self, document_id: str) -> list[dict]:
        return self._all("SELECT result_version, status, document_type, created_at FROM results WHERE document_id = ? "
                         "ORDER BY result_version", document_id)

    def result(self, document_id: str, version: int | None) -> dict | None:
        if version is None:
            row = self._one("SELECT body FROM results WHERE document_id = ? ORDER BY result_version DESC LIMIT 1", document_id)
        else:
            row = self._one("SELECT body FROM results WHERE document_id = ? AND result_version = ?", document_id, version)
        return None if row is None else json.loads(row["body"])
