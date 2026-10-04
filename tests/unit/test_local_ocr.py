import pytest

from edi_reference.adapters.local_ocr import LocalOcrProviderAdapter
from edi_reference.application.invocation import invoke_provider
from edi_reference.application.provider_conformance import assert_provider_adapter_conformant
from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass, ExecutionPolicy, ProviderCapability
from edi_reference.domain.invocation import InvocationLimits, InvocationRequest
from edi_reference.domain.provider import ProviderDescriptor


PROVIDER = ProviderCapability(
    "local-ocr", "1", ExecutionClass.OCR,
    frozenset({Capability.TEXT_EXTRACTION}), DataEgress.NONE,
)
DESCRIPTOR = ProviderDescriptor(PROVIDER, "local-ocr-adapter", "1")
LIMITS = InvocationLimits(10, 1024, 1024)


class Engine:
    def __init__(self):
        self.calls = []

    def extract_text(self, document_bytes, *, timeout_seconds):
        self.calls.append((document_bytes, timeout_seconds))
        return b"Invoice INV-001"


def request():
    return InvocationRequest(
        "attempt-1", Capability.TEXT_EXTRACTION, "local-ocr", "1",
        ExecutionClass.OCR, b"%PDF-synthetic",
    )


def test_local_ocr_runs_through_secure_invocation_boundary():
    engine = Engine()
    adapter = LocalOcrProviderAdapter(DESCRIPTOR, engine)
    result = invoke_provider(
        request(), provider=PROVIDER,
        policy=ExecutionPolicy("local-only", "1", frozenset({ExecutionClass.OCR}), False),
        limits=LIMITS, invoker=adapter,
    )
    assert result.output_bytes == b"Invoice INV-001"
    assert engine.calls == [(b"%PDF-synthetic", 10)]


def test_local_ocr_adapter_passes_provider_conformance():
    assert_provider_adapter_conformant(LocalOcrProviderAdapter(DESCRIPTOR, Engine()))


def test_local_ocr_rejects_non_ocr_descriptor():
    bad = ProviderDescriptor(
        ProviderCapability(
            "local-model", "1", ExecutionClass.LOCAL_MODEL,
            frozenset({Capability.TEXT_EXTRACTION}), DataEgress.NONE,
        ),
        "adapter", "1",
    )
    with pytest.raises(ValueError, match="LOCAL_OCR_REQUIRES_OCR_EXECUTION_CLASS"):
        LocalOcrProviderAdapter(bad, Engine())
