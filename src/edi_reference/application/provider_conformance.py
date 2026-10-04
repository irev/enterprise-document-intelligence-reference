"""Reusable conformance checks for provider adapters."""

from dataclasses import dataclass

from edi_reference.domain.execution import Capability, ExecutionClass
from edi_reference.domain.invocation import InvocationLimits, InvocationRequest
from edi_reference.domain.provider import ProviderAdapter


@dataclass(frozen=True, slots=True)
class ConformanceFinding:
    code: str
    passed: bool


def check_provider_adapter(adapter: ProviderAdapter) -> tuple[ConformanceFinding, ...]:
    descriptor = adapter.descriptor
    provider = descriptor.capability
    findings = [
        ConformanceFinding("DESCRIPTOR_VALID", bool(descriptor.adapter_id and descriptor.adapter_version)),
        ConformanceFinding("PROVIDER_ID_VALID", bool(provider.provider_id and provider.provider_version)),
        ConformanceFinding("CAPABILITIES_DECLARED", bool(provider.capabilities)),
    ]

    # Probe only contract rejection behavior. Conformance must never require
    # real network/model execution.
    unsupported = next(
        (item for item in Capability if item not in provider.capabilities),
        None,
    )
    if unsupported is not None:
        request = InvocationRequest(
            "conformance-probe", unsupported, provider.provider_id,
            provider.provider_version, provider.execution_class, b"",
        )
        try:
            adapter.invoke(request, InvocationLimits(1, 1, 1))
        except Exception:
            findings.append(ConformanceFinding("UNSUPPORTED_CAPABILITY_REJECTED", True))
        else:
            findings.append(ConformanceFinding("UNSUPPORTED_CAPABILITY_REJECTED", False))

    return tuple(findings)


def assert_provider_adapter_conformant(adapter: ProviderAdapter) -> None:
    failed = [item.code for item in check_provider_adapter(adapter) if not item.passed]
    if failed:
        raise ValueError("PROVIDER_ADAPTER_NONCONFORMANT:" + ",".join(failed))
