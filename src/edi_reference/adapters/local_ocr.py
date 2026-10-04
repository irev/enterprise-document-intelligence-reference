"""Dependency-free local OCR adapter using an injected engine port.

The adapter performs no network access and makes no provider-selection decisions.
Concrete OCR engines are integration packages, not core dependencies.
"""

from typing import Protocol

from edi_reference.domain.execution import Capability, DataEgress, ExecutionClass
from edi_reference.domain.invocation import InvocationLimits, InvocationRequest, InvocationResult
from edi_reference.domain.provider import ProviderAdapter, ProviderDescriptor


class LocalOcrEngine(Protocol):
    def extract_text(self, document_bytes: bytes, *, timeout_seconds: int) -> bytes: ...


class LocalOcrProviderAdapter(ProviderAdapter):
    def __init__(self, descriptor: ProviderDescriptor, engine: LocalOcrEngine):
        provider = descriptor.capability
        if provider.execution_class is not ExecutionClass.OCR:
            raise ValueError("LOCAL_OCR_REQUIRES_OCR_EXECUTION_CLASS")
        if provider.data_egress is not DataEgress.NONE:
            raise ValueError("LOCAL_OCR_MUST_NOT_DECLARE_EGRESS")
        if Capability.TEXT_EXTRACTION not in provider.capabilities:
            raise ValueError("LOCAL_OCR_REQUIRES_TEXT_EXTRACTION_CAPABILITY")
        self._descriptor = descriptor
        self._engine = engine

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def invoke(self, request: InvocationRequest, limits: InvocationLimits) -> InvocationResult:
        provider = self.descriptor.capability
        if request.capability is not Capability.TEXT_EXTRACTION:
            raise ValueError("UNSUPPORTED_CAPABILITY")
        if request.provider_id != provider.provider_id or request.provider_version != provider.provider_version:
            raise ValueError("PROVIDER_IDENTITY_MISMATCH")
        if request.execution_class is not ExecutionClass.OCR:
            raise ValueError("EXECUTION_CLASS_MISMATCH")
        output = self._engine.extract_text(request.input_bytes, timeout_seconds=limits.timeout_seconds)
        if not isinstance(output, bytes):
            raise ValueError("INVALID_OCR_ENGINE_OUTPUT")
        return InvocationResult(provider.provider_id, provider.provider_version, output)
