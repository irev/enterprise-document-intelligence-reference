from pathlib import Path

import pytest

from edi_reference.application.local_ocr_runtime import (
    parse_local_ocr_engine_ref,
    resolve_local_ocr_engine,
)
from edi_reference.application.provider_config import ProviderConfigurationRegistry
from edi_reference.domain.execution import (
    Capability,
    DataEgress,
    ExecutionClass,
    PlannedStep,
    ProviderCapability,
)
from edi_reference.domain.provider_config import ProviderConfiguration


PROVIDER = ProviderCapability(
    "paddle-ocr",
    "1",
    ExecutionClass.OCR,
    frozenset({Capability.TEXT_EXTRACTION, Capability.LAYOUT}),
    DataEgress.NONE,
)
STEP = PlannedStep(
    Capability.TEXT_EXTRACTION,
    "paddle-ocr",
    "1",
    ExecutionClass.OCR,
    "PROFILE",
)


def configuration(engine_ref: str, *, enabled: bool = True) -> ProviderConfiguration:
    return ProviderConfiguration(
        provider_id="paddle-ocr",
        config_version="1",
        enabled=enabled,
        deployment_zone="trusted-local",
        engine_ref=engine_ref,
        tenant_allowlist=frozenset({"tenant-a"}),
        application_allowlist=frozenset({("tenant-a", "app-a")}),
    )


def test_parse_versioned_connected_binding() -> None:
    result = parse_local_ocr_engine_ref(
        "paddle-ocr",
        "local-ocr:v1:nvidia:pp-ocrv6-medium:/models:CONNECTED",
    )

    assert result.profile == "nvidia"
    assert result.model_id == "pp-ocrv6-medium"
    assert result.model_root == Path("/models")
    assert not result.require_local_pinned


def test_parse_local_pinned_binding() -> None:
    result = parse_local_ocr_engine_ref(
        "paddle-ocr",
        "local-ocr:v1:cpu:pp-ocrv6-medium:/models:LOCAL_PINNED",
    )

    assert result.require_local_pinned


@pytest.mark.parametrize(
    "engine_ref",
    (
        "paddle",
        "local-ocr:v2:cpu:model:/models:CONNECTED",
        "local-ocr:v1::model:/models:CONNECTED",
        "local-ocr:v1:cpu::/models:CONNECTED",
        "local-ocr:v1:cpu:model::CONNECTED",
    ),
)
def test_invalid_binding_fails_closed(engine_ref: str) -> None:
    with pytest.raises(ValueError, match="INVALID_LOCAL_OCR_ENGINE_REF"):
        parse_local_ocr_engine_ref("paddle-ocr", engine_ref)


def test_unknown_storage_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="INVALID_LOCAL_OCR_STORAGE_POLICY"):
        parse_local_ocr_engine_ref(
            "paddle-ocr",
            "local-ocr:v1:cpu:model:/models:AUTO",
        )


def test_authorization_happens_before_engine_construction() -> None:
    configs = ProviderConfigurationRegistry(
        (
            configuration(
                "local-ocr:v1:cpu:pp-ocrv6-medium:/models:CONNECTED",
                enabled=False,
            ),
        )
    )

    with pytest.raises(Exception, match="PROVIDER_DISABLED"):
        resolve_local_ocr_engine(
            STEP,
            provider=PROVIDER,
            configurations=configs,
            tenant_id="tenant-a",
            application_id="app-a",
        )


def test_resolve_builds_isolated_engine_after_authorization() -> None:
    configs = ProviderConfigurationRegistry(
        (
            configuration(
                "local-ocr:v1:cpu:pp-ocrv6-medium:/models:CONNECTED",
            ),
        )
    )

    resolved, engine = resolve_local_ocr_engine(
        STEP,
        provider=PROVIDER,
        configurations=configs,
        tenant_id="tenant-a",
        application_id="app-a",
        timeout_seconds=30,
    )

    assert resolved.configuration.provider_id == "paddle-ocr"
    assert engine is not None
