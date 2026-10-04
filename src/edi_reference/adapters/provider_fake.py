"""No-network provider adapter used only for conformance tests."""

from edi_reference.domain.invocation import InvocationLimits, InvocationRequest, InvocationResult
from edi_reference.domain.provider import ProviderAdapter, ProviderDescriptor


class FakeProviderAdapter(ProviderAdapter):
    def __init__(self, descriptor: ProviderDescriptor):
        self._descriptor = descriptor

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def invoke(self, request: InvocationRequest, limits: InvocationLimits) -> InvocationResult:
        provider = self.descriptor.capability
        if request.capability not in provider.capabilities:
            raise ValueError("UNSUPPORTED_CAPABILITY")
        if request.provider_id != provider.provider_id:
            raise ValueError("PROVIDER_ID_MISMATCH")
        return InvocationResult(provider.provider_id, provider.provider_version, b"fake")
