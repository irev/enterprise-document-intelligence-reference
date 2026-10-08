"""Append-only, hash-chained audit log for control-panel actions (RI-4.11).

Each JSONL record carries the SHA-256 of the previous record, so editing or
deleting a line breaks the chain and `verify_chain` reports where. Records hold
actor, action, target and outcome; never passwords, tokens, keys or document
field values.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

GENESIS = "0" * 64
_FORBIDDEN_KEYS = {"password", "token", "csrf", "api_key", "authorization", "secret"}


def _digest(record: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path, *, now: Callable[[], str] | None = None) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(UTC).isoformat())
        self._lock = threading.Lock()
        self._last = self._tail_hash()

    def _tail_hash(self) -> str:
        if not self.path.is_file():
            return GENESIS
        last = GENESIS
        with self.path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    last = json.loads(line)["hash"]
        return last

    def record(self, actor: str, action: str, *, outcome: str = "OK", target: str | None = None,
               client: str | None = None, **details: object) -> dict[str, object]:
        if _FORBIDDEN_KEYS & {key.lower() for key in details}:
            raise ValueError("AUDIT_DETAIL_FORBIDDEN")
        with self._lock:
            body: dict[str, object] = {"ts": self._now(), "actor": actor, "action": action, "outcome": outcome,
                                       "target": target, "client": client, "details": details, "prev": self._last}
            body["hash"] = _digest(body)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(body, ensure_ascii=False) + "\n")
                stream.flush()
            self._last = str(body["hash"])
            return body

    def tail(self, limit: int = 200) -> list[dict[str, object]]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()][::-1]


def verify_chain(path: Path) -> tuple[bool, int | None]:
    """Return (intact, first broken 1-based line number or None)."""
    previous = GENESIS
    if not path.is_file():
        return True, None
    with path.open("r", encoding="utf-8") as stream:
        for number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                claimed = record.pop("hash")
            except (ValueError, KeyError):
                return False, number
            if record.get("prev") != previous or _digest(record) != claimed:
                return False, number
            previous = claimed
    return True, None
