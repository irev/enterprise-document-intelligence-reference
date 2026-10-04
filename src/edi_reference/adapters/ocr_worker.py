"""Process-isolated local OCR engine boundary with hard timeout."""

import multiprocessing as mp
from dataclasses import dataclass
from multiprocessing.context import BaseContext
from multiprocessing.process import BaseProcess
from typing import Callable, Protocol, cast

from edi_reference.adapters.local_ocr import LocalOcrEngine


class ProcessContext(Protocol):
    def Pipe(self, duplex: bool = ...) -> tuple[object, object]: ...
    def Process(self, *, target, args) -> BaseProcess: ...


@dataclass(frozen=True, slots=True)
class WorkerLimits:
    termination_grace_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.termination_grace_seconds < 0:
            raise ValueError("INVALID_WORKER_LIMITS")


def _run_engine(factory: Callable[[], LocalOcrEngine], document_bytes: bytes, timeout_seconds: int, connection) -> None:
    try:
        output = factory().extract_text(document_bytes, timeout_seconds=timeout_seconds)
        if not isinstance(output, bytes):
            connection.send(("ERROR", "INVALID_OCR_ENGINE_OUTPUT"))
        else:
            connection.send(("OK", output))
    except BaseException:
        try:
            connection.send(("ERROR", "OCR_WORKER_FAILED"))
        except BaseException:
            pass
    finally:
        connection.close()


class ProcessIsolatedOcrEngine:
    def __init__(
        self,
        engine_factory: Callable[[], LocalOcrEngine],
        *,
        worker_limits: WorkerLimits = WorkerLimits(),
        start_method: str = "spawn",
    ):
        self._factory = engine_factory
        self._limits = worker_limits
        self._context = cast(ProcessContext, mp.get_context(start_method))

    def extract_text(self, document_bytes: bytes, *, timeout_seconds: int) -> bytes:
        if timeout_seconds <= 0:
            raise ValueError("INVALID_OCR_TIMEOUT")
        parent, child = self._context.Pipe(duplex=False)
        process = self._context.Process(
            target=_run_engine,
            args=(self._factory, document_bytes, timeout_seconds, child),
        )
        process.start()
        child.close()
        try:
            if not parent.poll(timeout_seconds):
                process.terminate()
                process.join(self._limits.termination_grace_seconds)
                if process.is_alive():
                    process.kill()
                    process.join()
                raise TimeoutError("OCR_WORKER_TIMEOUT")
            try:
                message = parent.recv()
            except (EOFError, OSError):
                raise RuntimeError("OCR_WORKER_FAILED") from None
            process.join(self._limits.termination_grace_seconds)
            if process.is_alive():
                process.terminate()
                process.join()
            if not isinstance(message, tuple) or len(message) != 2:
                raise RuntimeError("OCR_WORKER_FAILED")
            status, payload = message
            if status == "ERROR":
                raise RuntimeError(str(payload))
            if status != "OK" or not isinstance(payload, bytes):
                raise RuntimeError("OCR_WORKER_FAILED")
            return payload
        finally:
            parent.close()
