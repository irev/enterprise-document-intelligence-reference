"""File-level processing audit: page analysis output and JSONL processing log."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from edi_reference.domain.ocr import OcrResult


@dataclass(frozen=True, slots=True)
class PageAnalysis:
    page_number: int
    line_count: int
    character_count: int


@dataclass(frozen=True, slots=True)
class FileProcessingReport:
    file_id: str
    source_name: str
    sha256: str
    status: str
    total_pages: int
    pages: tuple[PageAnalysis, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ProcessingLog:
    """Append-only processing event log, optionally persisted as JSONL."""

    def __init__(
        self,
        *,
        sink_path: Path | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self._sink_path = sink_path
        self._now = now or (lambda: datetime.now(UTC).isoformat())
        self.events: list[dict[str, object]] = []

    def record(self, event: str, **fields: object) -> dict[str, object]:
        record: dict[str, object] = {"event": event, "ts": self._now(), **fields}
        self.events.append(record)
        if self._sink_path is not None:
            self._sink_path.parent.mkdir(parents=True, exist_ok=True)
            with self._sink_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
                handle.flush()
        return record


def analyze_ocr_pages(result: OcrResult) -> tuple[PageAnalysis, ...]:
    return tuple(
        PageAnalysis(
            page_number=page.page_number,
            line_count=len(page.lines),
            character_count=sum(len(line.text) for line in page.lines),
        )
        for page in result.pages
    )


def process_file(
    *,
    source_name: str,
    document_bytes: bytes,
    analyze: Callable[[bytes], OcrResult],
    log: ProcessingLog,
) -> FileProcessingReport:
    """Process one file through a page-producing analyzer with audit logging.

    The analyzer failure is recorded as FILE_PROCESSING_FAILED and re-raised;
    caller-visible failure behavior is unchanged.
    """
    digest = hashlib.sha256(document_bytes).hexdigest()
    file_id = digest
    log.record(
        "FILE_PROCESSING_STARTED",
        file_id=file_id,
        source_name=source_name,
        sha256=digest,
    )
    try:
        result = analyze(document_bytes)
    except Exception as exc:
        log.record(
            "FILE_PROCESSING_FAILED",
            file_id=file_id,
            error_code=str(exc) or exc.__class__.__name__,
        )
        raise
    pages = analyze_ocr_pages(result)
    for page in pages:
        log.record(
            "PAGE_ANALYZED",
            file_id=file_id,
            page_number=page.page_number,
            line_count=page.line_count,
            character_count=page.character_count,
        )
    report = FileProcessingReport(
        file_id=file_id,
        source_name=source_name,
        sha256=digest,
        status="COMPLETED",
        total_pages=len(pages),
        pages=pages,
    )
    log.record(
        "FILE_PROCESSING_COMPLETED",
        file_id=file_id,
        status=report.status,
        total_pages=report.total_pages,
        pages_analyzed=len(pages),
    )
    return report
