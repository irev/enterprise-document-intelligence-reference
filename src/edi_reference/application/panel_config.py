"""Versioned control-panel configuration (RI-4.11).

Every save creates a new immutable version; activation is a separate pointer,
so rolling back never rewrites history. Each kind is validated before it is
stored, and documents can never change configuration.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from edi_reference.application.title_rules import title_rule_profile_from_dict
from edi_reference.domain.field_schema import ExtractionSchema, FieldDefinition

KINDS = ("title_rules", "extraction_schema", "pipeline")
FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
VALUE_TYPES = {"string", "date", "money", "identifier"}
MODES = ("rules", "rules_then_llm", "llm")


def schema_from_dict(raw: object) -> ExtractionSchema:
    if not isinstance(raw, dict) or not isinstance(raw.get("fields"), list) or not 1 <= len(raw["fields"]) <= 50:
        raise ValueError("INVALID_EXTRACTION_SCHEMA")
    fields = []
    for item in raw["fields"]:
        if not isinstance(item, dict) or not FIELD_NAME.fullmatch(str(item.get("field_name", ""))):
            raise ValueError("INVALID_FIELD_NAME")
        if item.get("value_type") not in VALUE_TYPES:
            raise ValueError("INVALID_FIELD_VALUE_TYPE")
        fields.append(FieldDefinition(item["field_name"], item["value_type"]))
    return ExtractionSchema(str(raw.get("schema_id", "")), str(raw.get("version", "")), tuple(fields))


def validate_pipeline(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("INVALID_PIPELINE_CONFIG")
    llm = raw.get("llm", {})
    ocr = raw.get("ocr", {})
    if not isinstance(llm, dict) or not isinstance(ocr, dict):
        raise ValueError("INVALID_PIPELINE_CONFIG")
    if not ipaddress.ip_address(str(llm.get("host", "127.0.0.1"))).is_loopback:
        raise ValueError("LLM_ENDPOINT_MUST_BE_LOOPBACK")
    if type(llm.get("port")) is not int or not 1 <= llm["port"] <= 65535:
        raise ValueError("INVALID_LLM_PORT")
    if not isinstance(llm.get("model"), str) or not llm["model"].strip() or len(llm["model"]) > 200:
        raise ValueError("INVALID_LLM_MODEL")
    if raw.get("classification_mode") not in MODES:
        raise ValueError("INVALID_CLASSIFICATION_MODE")
    if type(raw.get("max_pages")) is not int or not 1 <= raw["max_pages"] <= 20:
        raise ValueError("INVALID_MAX_PAGES")
    for key in ("det_name", "det_dir", "rec_name", "rec_dir"):
        if not isinstance(ocr.get(key), str) or not ocr[key].strip():
            raise ValueError("INVALID_OCR_CONFIG")
    return raw


VALIDATORS: dict[str, Callable[[object], object]] = {
    "title_rules": title_rule_profile_from_dict,
    "extraction_schema": schema_from_dict,
    "pipeline": validate_pipeline,
}


class ConfigStore:
    def __init__(self, root: Path, *, now: Callable[[], str] | None = None) -> None:
        self.root = root
        self._now = now or (lambda: datetime.now(UTC).isoformat())
        self._lock = threading.Lock()

    def _dir(self, kind: str) -> Path:
        if kind not in KINDS:
            raise ValueError("UNKNOWN_CONFIG_KIND")
        return self.root / kind

    def versions(self, kind: str) -> list[dict]:
        directory = self._dir(kind)
        out = []
        for path in sorted(directory.glob("v*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            out.append({key: record[key] for key in ("version", "created_at", "author", "comment")})
        return out

    def get(self, kind: str, version: int | None = None) -> dict:
        directory = self._dir(kind)
        number = version if version is not None else self.active_version(kind)
        if number is None:
            raise LookupError("CONFIG_NOT_FOUND")
        path = directory / f"v{number:05d}.json"
        if not path.is_file():
            raise LookupError("CONFIG_NOT_FOUND")
        return json.loads(path.read_text(encoding="utf-8"))

    def active_version(self, kind: str) -> int | None:
        pointer = self._dir(kind) / "active.json"
        if not pointer.is_file():
            return None
        return int(json.loads(pointer.read_text(encoding="utf-8"))["version"])

    def active(self, kind: str) -> dict:
        return self.get(kind)["content"]

    def save(self, kind: str, content: dict, *, author: str, comment: str = "", activate: bool = True) -> int:
        self._dir(kind)
        VALIDATORS[kind](content)
        if len(comment) > 500:
            raise ValueError("COMMENT_TOO_LONG")
        with self._lock:
            directory = self._dir(kind)
            directory.mkdir(parents=True, exist_ok=True)
            existing = [int(p.stem[1:]) for p in directory.glob("v*.json")]
            number = max(existing, default=0) + 1
            record = {"version": number, "created_at": self._now(), "author": author, "comment": comment,
                      "content": content}
            path = directory / f"v{number:05d}.json"
            # "x" mode: an existing version is never overwritten.
            with path.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False, indent=1)
            if activate:
                self._point(directory, number)
            return number

    def activate(self, kind: str, version: int) -> None:
        self.get(kind, version)
        with self._lock:
            self._point(self._dir(kind), version)

    @staticmethod
    def _point(directory: Path, version: int) -> None:
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".active-", suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"version": version}, stream)
        os.replace(temporary, directory / "active.json")

    def seed(self, kind: str, content: dict, *, author: str = "system") -> None:
        if self.active_version(kind) is None:
            self.save(kind, content, author=author, comment="initial default")
