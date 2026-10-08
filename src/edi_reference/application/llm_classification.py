"""Model-assisted classification that must quote its evidence (RI-4.11).

The model picks a taxonomy type (or UNKNOWN) and quotes the source line that
supports it. The candidate is returned only when that quote is found in a
source text block; otherwise there is no candidate and classification
abstains to UNKNOWN. Used as a fallback after deterministic title rules.
"""

from __future__ import annotations

import json
import uuid
from typing import Callable

from edi_reference.application.classification import RawClassification
from edi_reference.application.invocation import ProviderInvocationError, ProviderInvoker, invoke_provider
from edi_reference.application.llm_extraction import locate_quote
from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE, ClassificationCandidate
from edi_reference.domain.document_structure import StructuredDocument
from edi_reference.domain.evidence import EvidenceKind, EvidenceReference
from edi_reference.domain.execution import Capability, ExecutionPolicy, ProviderCapability
from edi_reference.domain.invocation import InvocationFailureCode, InvocationLimits, InvocationRequest
from edi_reference.domain.taxonomy import DocumentTaxonomy

CLASSIFICATION_MEDIA_TYPE = "application/vnd.edi.classification-request+json"
MAX_LINES = 200


class LlmClassifier:
    def __init__(self, *, taxonomy: DocumentTaxonomy, provider: ProviderCapability, policy: ExecutionPolicy,
                 limits: InvocationLimits, invoker: ProviderInvoker,
                 attempt_id: Callable[[], str] = lambda: str(uuid.uuid4())) -> None:
        if Capability.CLASSIFICATION not in provider.capabilities:
            raise ValueError("PROVIDER_LACKS_CLASSIFICATION")
        self.model_id = f"llm-grounded/{provider.provider_id}"
        self.model_version = provider.provider_version
        self.taxonomy_version = taxonomy.version
        self._types = sorted(taxonomy.document_types)
        self._provider, self._policy, self._limits = provider, policy, limits
        self._invoker, self._attempt_id = invoker, attempt_id

    def classify(self, document: StructuredDocument) -> RawClassification:
        blocks = [(page.page_number, block) for page in document.pages
                  for block in sorted(page.text_blocks, key=lambda item: item.reading_order)][:MAX_LINES]
        request = InvocationRequest(
            attempt_id=self._attempt_id(), capability=Capability.CLASSIFICATION,
            provider_id=self._provider.provider_id, provider_version=self._provider.provider_version,
            execution_class=self._provider.execution_class,
            input_bytes=json.dumps({"media_type": CLASSIFICATION_MEDIA_TYPE,
                                    "document_types": self._types + [UNKNOWN_DOCUMENT_TYPE],
                                    "lines": [block.text for _, block in blocks]}, ensure_ascii=False).encode("utf-8"),
        )
        result = invoke_provider(request, provider=self._provider, policy=self._policy, limits=self._limits,
                                 invoker=self._invoker)
        try:
            answer = json.loads(result.output_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderInvocationError(InvocationFailureCode.INVALID_PROVIDER_RESPONSE) from None
        document_type = answer.get("document_type") if isinstance(answer, dict) else None
        quote = answer.get("evidence") if isinstance(answer, dict) else None
        if document_type not in self._types or not isinstance(quote, str) or not quote.strip():
            return RawClassification((), ())
        located = locate_quote(blocks, quote.strip())
        if located is None:
            return RawClassification((), ())
        page_number, block, text = located
        evidence = EvidenceReference(document.observation_id, document.observation_sha256, page_number,
                                     EvidenceKind.TEXT_BLOCK, block_id=block.block_id, text_quote=text)
        return RawClassification((ClassificationCandidate(document_type, 1.0),), (evidence,))
