"""Control-panel identities, sessions and login throttling (RI-4.11).

Standard library only. Passwords are stored as PBKDF2-HMAC-SHA256 hashes with
a per-user salt; sessions are random bearer tokens held in memory only, so a
restart signs everyone out. Panel roles authorize panel operations only; they
never authorize business actions on documents.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Callable

PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD_LENGTH = 12
USERNAME_PATTERN = re.compile(r"[a-z][a-z0-9._-]{1,31}")


class Role(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3


@dataclass(frozen=True, slots=True)
class PanelUser:
    username: str
    role: Role
    salt: str
    password_hash: str
    iterations: int
    disabled: bool = False


def _hash(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations).hex()


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH or len(password) > 256:
        raise ValueError("PASSWORD_TOO_WEAK")
    if password.isdigit() or password.isalpha() or len(set(password)) < 6:
        raise ValueError("PASSWORD_TOO_WEAK")


class UserStore:
    """JSON file of panel users; written atomically, never containing plaintext."""

    def __init__(self, path: Path, *, iterations: int = PBKDF2_ITERATIONS) -> None:
        self.path = path
        self._iterations = iterations
        self._lock = threading.Lock()

    def _load(self) -> dict[str, PanelUser]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        users = {}
        for item in raw.get("users", []):
            user = PanelUser(item["username"], Role[item["role"]], item["salt"], item["password_hash"],
                             int(item["iterations"]), bool(item.get("disabled", False)))
            users[user.username] = user
        return users

    def _save(self, users: dict[str, PanelUser]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "users": [
            {"username": u.username, "role": u.role.name, "salt": u.salt, "password_hash": u.password_hash,
             "iterations": u.iterations, "disabled": u.disabled} for u in sorted(users.values(), key=lambda u: u.username)
        ]}
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".users-", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=1)
        os.replace(temporary, self.path)

    def all_users(self) -> list[PanelUser]:
        return sorted(self._load().values(), key=lambda u: u.username)

    def get(self, username: str) -> PanelUser | None:
        return self._load().get(username)

    def upsert(self, username: str, password: str | None, role: Role | None = None, *, disabled: bool | None = None) -> PanelUser:
        if not USERNAME_PATTERN.fullmatch(username):
            raise ValueError("INVALID_USERNAME")
        with self._lock:
            users = self._load()
            current = users.get(username)
            if current is None and (password is None or role is None):
                raise ValueError("NEW_USER_REQUIRES_PASSWORD_AND_ROLE")
            salt, digest, iterations = (current.salt, current.password_hash, current.iterations) if current else ("", "", 0)
            if password is not None:
                validate_password(password)
                raw_salt = secrets.token_bytes(16)
                salt, digest, iterations = raw_salt.hex(), _hash(password, raw_salt, self._iterations), self._iterations
            user = PanelUser(
                username,
                role if role is not None else current.role,  # type: ignore[union-attr]
                salt,
                digest,
                iterations,
                disabled if disabled is not None else (current.disabled if current else False),
            )
            users[username] = user
            if not any(u.role is Role.ADMIN and not u.disabled for u in users.values()):
                raise ValueError("AT_LEAST_ONE_ACTIVE_ADMIN_REQUIRED")
            self._save(users)
            return user

    def verify(self, username: str, password: str) -> PanelUser | None:
        user = self._load().get(username)
        if user is None:
            # Equalize timing for unknown users.
            _hash(password, b"\0" * 16, self._iterations)
            return None
        ok = hmac.compare_digest(_hash(password, bytes.fromhex(user.salt), user.iterations), user.password_hash)
        return user if ok and not user.disabled else None


@dataclass(slots=True)
class Session:
    token: str
    csrf: str
    username: str
    role: Role
    created: float
    last_seen: float


class SessionManager:
    def __init__(self, *, idle_seconds: int = 1800, absolute_seconds: int = 12 * 3600,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._sessions: dict[str, Session] = {}
        self._idle, self._absolute, self._clock = idle_seconds, absolute_seconds, clock
        self._lock = threading.Lock()

    def create(self, user: PanelUser) -> Session:
        now = self._clock()
        session = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(32), user.username, user.role, now, now)
        with self._lock:
            self._sessions[session.token] = session
        return session

    def get(self, token: str | None) -> Session | None:
        if not token:
            return None
        now = self._clock()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if now - session.last_seen > self._idle or now - session.created > self._absolute:
                del self._sessions[token]
                return None
            session.last_seen = now
            return session

    def revoke(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def revoke_user(self, username: str) -> None:
        with self._lock:
            for token in [t for t, s in self._sessions.items() if s.username == username]:
                del self._sessions[token]


class LoginThrottle:
    """Locks a username or client address after repeated failures."""

    def __init__(self, *, max_failures: int = 5, window_seconds: int = 900, lock_seconds: int = 900,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._max, self._window, self._lock_for, self._clock = max_failures, window_seconds, lock_seconds, clock
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def blocked(self, *keys: str) -> bool:
        now = self._clock()
        with self._lock:
            return any(self._locked_until.get(key, 0) > now for key in keys)

    def failure(self, *keys: str) -> None:
        now = self._clock()
        with self._lock:
            for key in keys:
                recent = [t for t in self._failures.get(key, []) if now - t < self._window] + [now]
                self._failures[key] = recent
                if len(recent) >= self._max:
                    self._locked_until[key] = now + self._lock_for
                    self._failures[key] = []

    def success(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._failures.pop(key, None)
