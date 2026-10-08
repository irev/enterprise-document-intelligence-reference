"""Model-assisted field extraction grounded in source text blocks (RI-4.10).

The model is invoked only through the provider invocation boundary. Its answer
is a claim: a value becomes PRESENT only when it is found verbatim (modulo
whitespace) inside a source text block, which then becomes its evidence.
Ungrounded or malformed values are dropped to MISSING; nothing is invented.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Callable

from edi_reference.application.invocation import ProviderInvocationError, ProviderInvoker, invoke_provider
from edi_reference.domain.document_structure import StructuredDocument, TextBlock
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.execution import Capability, ExecutionPolicy, ProviderCapability
from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.field_schema import ExtractionSchema
from edi_reference.domain.invocation import (
    InvocationFailureCode,
    InvocationLimits,
    InvocationRequest,
)

REQUEST_MEDIA_TYPE = "application/vnd.edi.field-extraction-request+json"
MAX_VALUE_LENGTH = 500


class LlmFieldExtractor:
    """ExtractorAdapter that asks a model for verbatim values and grounds them."""

    def __init__(
        self,
        *,
        schema: ExtractionSchema,
        provider: ProviderCapability,
        policy: ExecutionPolicy,
        limits: InvocationLimits,
        invoker: ProviderInvoker,
        attempt_id: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        if Capability.FIELD_EXTRACTION not in provider.capabilities:
            raise ValueError("PROVIDER_LACKS_FIELD_EXTRACTION")
        self.extractor_id = f"llm-grounded/{provider.provider_id}"
        self.extractor_version = provider.provider_version
        self.schema_version = schema.version
        self._schema = schema
        self._provider = provider
        self._policy = policy
        self._limits = limits
        self._invoker = invoker
        self._attempt_id = attempt_id

    def extract(self, document: StructuredDocument, document_type: str) -> tuple[ExtractedField, ...]:
        blocks = [
            (page.page_number, block)
            for page in document.pages
            for block in sorted(page.text_blocks, key=lambda item: item.reading_order)
        ]
        request = InvocationRequest(
            attempt_id=self._attempt_id(),
            capability=Capability.FIELD_EXTRACTION,
            provider_id=self._provider.provider_id,
            provider_version=self._provider.provider_version,
            execution_class=self._provider.execution_class,
            input_bytes=json.dumps(
                {
                    "media_type": REQUEST_MEDIA_TYPE,
                    "document_type": document_type,
                    "fields": [
                        {"name": item.field_name, "value_type": item.value_type}
                        for item in self._schema.fields
                    ],
                    "lines": [block.text for _, block in blocks],
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        result = invoke_provider(
            request,
            provider=self._provider,
            policy=self._policy,
            limits=self._limits,
            invoker=self._invoker,
        )
        values = _decode_values(result.output_bytes)
        return tuple(
            self._ground(document, blocks, item.field_name, item.value_type, values.get(item.field_name))
            for item in self._schema.fields
        )

    def _ground(
        self,
        document: StructuredDocument,
        blocks: list[tuple[int, TextBlock]],
        field_name: str,
        value_type: str,
        value: object,
    ) -> ExtractedField:
        if isinstance(value, str) and 0 < len(value.strip()) <= MAX_VALUE_LENGTH:
            located = locate_quote(blocks, value.strip())
            if located is not None:
                page_number, block, quote = located
                evidence = EvidenceReference(
                    observation_id=document.observation_id,
                    observation_sha256=document.observation_sha256,
                    page_number=page_number,
                    kind=EvidenceKind.TEXT_BLOCK,
                    block_id=block.block_id,
                    text_quote=quote,
                )
                return self._field(field_name, value_type, FieldState.PRESENT, quote, (evidence,))
        return self._field(field_name, value_type, FieldState.MISSING, None, ())

    def _field(self, name, value_type, state, raw_value, evidence) -> ExtractedField:
        return ExtractedField(
            field_name=name,
            state=state,
            raw_value=raw_value,
            value_type=value_type,
            confidence=None,
            evidence=evidence,
            extractor_id=self.extractor_id,
            extractor_version=self.extractor_version,
            schema_version=self.schema_version,
        )


def _decode_values(output: bytes) -> dict[str, object]:
    try:
        payload = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE) from None
    fields = payload.get("fields") if isinstance(payload, dict) else None
    if not isinstance(fields, dict):
        raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE)
    return fields


def locate_quote(blocks: list[tuple[int, TextBlock]], value: str) -> tuple[int, TextBlock, str] | None:
    pattern = re.compile(r"\s+".join(re.escape(token) for token in value.split()))
    for page_number, block in blocks:
        match = pattern.search(block.text)
        if match is not None:
            return page_number, block, match.group(0)
    return None
