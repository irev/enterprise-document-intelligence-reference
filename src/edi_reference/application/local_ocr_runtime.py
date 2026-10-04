"""Resolve authorized local OCR configuration into an isolated provider invoker."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edi_reference.adapters.local_ocr import ProcessIsolatedOcrEngine
from edi_reference.adapters.paddle_pipeline import (
    PaddleOcrEngineFactory,
    PaddlePipelineConfiguration,
)
from edi_reference.application.provider_config import ProviderConfigurationSource
from edi_reference.application.planned_provider import authorize_planned_provider
from edi_reference.domain.execution import (
    Capability,
    ExecutionClass,
    PlannedStep,
    ProviderCapability,
)
from edi_reference.domain.provider_config import ResolvedProvider


@dataclass(frozen=True, slots=True)
class LocalOcrBinding:
    provider_id: str
    profile: str
    model_id: str
    model_root: Path
    require_local_pinned: bool


def parse_local_ocr_engine_ref(provider_id: str, engine_ref: str) -> LocalOcrBinding:
    """Parse the temporary versioned engine-ref contract.

    Format:
      local-ocr:v1:<profile>:<model_id>:<model_root>:<storage-policy>

    storage-policy is CONNECTED or LOCAL_PINNED.
    """
    parts = engine_ref.split(":", 5)
    if len(parts) != 6 or parts[0:2] != ["local-ocr", "v1"]:
        raise ValueError("INVALID_LOCAL_OCR_ENGINE_REF")
    _, _, profile, model_id, model_root, storage_policy = parts
    if not profile or not model_id or not model_root:
        raise ValueError("INVALID_LOCAL_OCR_ENGINE_REF")
    if storage_policy not in {"CONNECTED", "LOCAL_PINNED"}:
        raise ValueError("INVALID_LOCAL_OCR_STORAGE_POLICY")
    return LocalOcrBinding(
        provider_id=provider_id,
        profile=profile,
        model_id=model_id,
        model_root=Path(model_root),
        require_local_pinned=storage_policy == "LOCAL_PINNED",
    )


def resolve_local_ocr_engine(
    step: PlannedStep,
    *,
    provider: ProviderCapability,
    configurations: ProviderConfigurationSource,
    tenant_id: str,
    application_id: str,
    timeout_seconds: float = 120.0,
) -> tuple[ResolvedProvider, ProcessIsolatedOcrEngine]:
    if step.capability not in {Capability.TEXT_EXTRACTION, Capability.LAYOUT}:
        raise ValueError("LOCAL_OCR_CAPABILITY_REQUIRED")
    if step.execution_class is not ExecutionClass.OCR:
        raise ValueError("LOCAL_OCR_EXECUTION_CLASS_REQUIRED")

    resolved = authorize_planned_provider(
        step,
        provider=provider,
        configurations=configurations,
        tenant_id=tenant_id,
        application_id=application_id,
    )
    binding = parse_local_ocr_engine_ref(
        resolved.configuration.provider_id,
        resolved.configuration.engine_ref,
    )
    if binding.provider_id != "paddle-ocr":
        raise ValueError("UNSUPPORTED_LOCAL_OCR_PROVIDER")
    if binding.profile not in {"cpu", "nvidia"}:
        raise ValueError("UNSUPPORTED_PADDLE_PROFILE")

    factory = PaddleOcrEngineFactory(
        PaddlePipelineConfiguration(
            model_id=binding.model_id,
            model_root=binding.model_root,
            require_local_pinned=binding.require_local_pinned,
        )
    )
    return resolved, ProcessIsolatedOcrEngine(factory, timeout_seconds=timeout_seconds)
