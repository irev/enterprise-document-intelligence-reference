import pytest

from edi_reference.adapters.provider_fake import FakeProviderAdapter
from edi_reference.application.provider_conformance import (
    assert_provider_adapter_conformant, check_provider_adapter,
)
from edi_reference.domain.execution import (
    Capability, DataEgress, ExecutionClass, ProviderCapability,
)
from edi_reference.domain.provider import ProviderAdapter, ProviderDescriptor


def descriptor():
    return ProviderDescriptor(
        ProviderCapability(
            "local-test", "1", ExecutionClass.LOCAL_MODEL,
            frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
        ),
        "fake-adapter", "1",
    )


def test_fake_adapter_passes_contract_conformance():
    adapter = FakeProviderAdapter(descriptor())
    assert_provider_adapter_conformant(adapter)
    assert all(item.passed for item in check_provider_adapter(adapter))


class BadAdapter(ProviderAdapter):
    @property
    def descriptor(self):
        return descriptor()

    def invoke(self, request, limits):
        provider = self.descriptor.capability
        return __import__("edi_reference.domain.invocation", fromlist=["InvocationResult"]).InvocationResult(
            provider.provider_id, provider.provider_version, b"bad"
        )


def test_adapter_that_accepts_unsupported_capability_fails_conformance():
    with pytest.raises(ValueError, match="PROVIDER_ADAPTER_NONCONFORMANT"):
        assert_provider_adapter_conformant(BadAdapter())


def test_remote_provider_must_declare_external_egress():
    with pytest.raises(ValueError, match="REMOTE_PROVIDER_MUST_DECLARE_EXTERNAL_EGRESS"):
        ProviderDescriptor(
            ProviderCapability(
                "remote-test", "1", ExecutionClass.REMOTE_MODEL,
                frozenset({Capability.CLASSIFICATION}), DataEgress.NONE,
            ),
            "remote-adapter", "1",
        )


def test_local_provider_cannot_declare_external_egress():
    with pytest.raises(ValueError, match="NON_REMOTE_PROVIDER_CANNOT_DECLARE_EXTERNAL_EGRESS"):
        ProviderDescriptor(
            ProviderCapability(
                "local-test", "1", ExecutionClass.LOCAL_MODEL,
                frozenset({Capability.CLASSIFICATION}), DataEgress.APPROVED_EXTERNAL,
            ),
            "local-adapter", "1",
        )
