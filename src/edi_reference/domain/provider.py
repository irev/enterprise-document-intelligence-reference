"""Provider adapter contract and conformance vocabulary."""

from dataclasses import dataclass

from edi_reference.domain.execution import ProviderCapability
from edi_reference.domain.invocation import InvocationLimits, InvocationRequest, InvocationResult


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    capability: ProviderCapability
    adapter_id: str
    adapter_version: str

    def __post_init__(self) -> None:
        if not self.adapter_id or not self.adapter_version:
            raise ValueError("INVALID_PROVIDER_DESCRIPTOR")


class ProviderAdapter:
    """Minimal provider SPI. Implementations must not make policy decisions."""

    @property
    def descriptor(self) -> ProviderDescriptor:
        raise NotImplementedError

    def invoke(self, request: InvocationRequest, limits: InvocationLimits) -> InvocationResult:
        raise NotImplementedError
