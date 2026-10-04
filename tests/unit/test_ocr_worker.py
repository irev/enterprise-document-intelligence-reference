import time

import pytest

from edi_reference.adapters.ocr_worker import ProcessIsolatedOcrEngine, WorkerLimits


class EchoEngine:
    def extract_text(self, document_bytes, *, timeout_seconds):
        return b"ocr:" + document_bytes


class SlowEngine:
    def extract_text(self, document_bytes, *, timeout_seconds):
        time.sleep(timeout_seconds + 2)
        return b"late"


class CrashEngine:
    def extract_text(self, document_bytes, *, timeout_seconds):
        raise RuntimeError("engine secret")


def echo_factory():
    return EchoEngine()


def slow_factory():
    return SlowEngine()


def crash_factory():
    return CrashEngine()


def test_worker_returns_engine_output():
    engine = ProcessIsolatedOcrEngine(echo_factory)
    assert engine.extract_text(b"doc", timeout_seconds=2) == b"ocr:doc"


def test_worker_enforces_hard_timeout():
    engine = ProcessIsolatedOcrEngine(slow_factory, worker_limits=WorkerLimits(.1))
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="OCR_WORKER_TIMEOUT"):
        engine.extract_text(b"doc", timeout_seconds=1)
    assert time.monotonic() - started < 2


def test_worker_sanitizes_engine_failure():
    engine = ProcessIsolatedOcrEngine(crash_factory)
    with pytest.raises(RuntimeError, match="OCR_WORKER_FAILED") as caught:
        engine.extract_text(b"doc", timeout_seconds=2)
    assert "engine secret" not in str(caught.value)
