"""Atomic PostgreSQL finalization of a durable processing result."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any

from edi_reference.domain.processing_result import ProcessingResult


class ProcessingFinalizationRejected(RuntimeError):
    pass


class PostgreSqlProcessingResultFinalizer:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def finalize(
        self,
        *,
        message_id: str,
        expected_generation: int,
        result: ProcessingResult,
        completed_at: datetime,
    ) -> None:
        """Persist the complete result and complete its claim in one transaction."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT processing_run_id, tenant_id, application_id,
                              observation_id, observation_sha256, status, lease_until,
                              claim_generation
                       FROM processing.processing_claim
                       WHERE message_id=%s
                       FOR UPDATE""",
                    (message_id,),
                )
                claim = cursor.fetchone()
                if claim is None:
                    raise ProcessingFinalizationRejected("CLAIM_NOT_FOUND")
                if (
                    claim[5] != "CLAIMED"
                    or claim[7] != expected_generation
                    or claim[6] <= completed_at
                ):
                    raise ProcessingFinalizationRejected("CLAIM_OWNERSHIP_LOST")
                if (
                    claim[0] != result.processing_run_id
                    or claim[1] != result.tenant_id
                    or claim[2] != result.application_id
                    or claim[3] != result.observation_id
                    or claim[4] != result.observation_sha256
                ):
                    raise ProcessingFinalizationRejected("RESULT_CLAIM_LINEAGE_MISMATCH")

                cursor.execute(
                    """INSERT INTO processing.processing_result
                       (result_id,result_version,processing_run_id,document_id,
                        tenant_id,application_id,observation_id,observation_sha256,
                        schema_version,created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        result.result_id, result.result_version,
                        result.processing_run_id, result.document_id,
                        result.tenant_id, result.application_id,
                        result.observation_id, result.observation_sha256,
                        result.schema_version, result.created_at,
                    ),
                )
                prediction = result.classification
                cursor.execute(
                    """INSERT INTO processing.classification_result
                       (result_id,result_version,document_type,confidence,model_id,
                        model_version,taxonomy_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        result.result_id, result.result_version,
                        prediction.document_type, prediction.confidence,
                        prediction.model_id, prediction.model_version,
                        prediction.taxonomy_version,
                    ),
                )
                for ordinal, alternative in enumerate(prediction.alternatives):
                    cursor.execute(
                        """INSERT INTO processing.classification_alternative
                           (result_id,result_version,alternative_ordinal,
                            document_type,confidence)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (
                            result.result_id, result.result_version, ordinal,
                            alternative.document_type, alternative.confidence,
                        ),
                    )

                evidence_ordinals: dict[Any, int] = {}

                def evidence_ordinal(evidence) -> int:
                    ordinal = evidence_ordinals.get(evidence)
                    if ordinal is None:
                        ordinal = len(evidence_ordinals)
                        evidence_ordinals[evidence] = ordinal
                    return ordinal

                for evidence in prediction.evidence:
                    evidence_ordinal(evidence)
                for field in result.fields:
                    for evidence in field.extracted.evidence:
                        evidence_ordinal(evidence)

                for evidence, ordinal in evidence_ordinals.items():
                    bbox = evidence.bbox
                    cursor.execute(
                        """INSERT INTO processing.evidence_reference
                           (result_id,result_version,evidence_ordinal,observation_id,
                            observation_sha256,page_number,kind,block_id,table_row,
                            table_column,bbox_x0,bbox_y0,bbox_x1,bbox_y1,text_quote)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            result.result_id, result.result_version, ordinal,
                            evidence.observation_id, evidence.observation_sha256,
                            evidence.page_number, evidence.kind.value, evidence.block_id,
                            evidence.row, evidence.column,
                            None if bbox is None else bbox.x0,
                            None if bbox is None else bbox.y0,
                            None if bbox is None else bbox.x1,
                            None if bbox is None else bbox.y1,
                            evidence.text_quote,
                        ),
                    )
                for link_ordinal, evidence in enumerate(prediction.evidence):
                    cursor.execute(
                        """INSERT INTO processing.classification_evidence
                           (result_id,result_version,evidence_ordinal,link_ordinal)
                           VALUES (%s,%s,%s,%s)""",
                        (
                            result.result_id, result.result_version,
                            evidence_ordinal(evidence), link_ordinal,
                        ),
                    )

                for field_ordinal, field in enumerate(result.fields):
                    extracted = field.extracted
                    cursor.execute(
                        """INSERT INTO processing.extracted_field
                           (result_id,result_version,field_ordinal,field_name,state,
                            raw_value,value_type,confidence,extractor_id,
                            extractor_version,schema_version)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            result.result_id, result.result_version, field_ordinal,
                            extracted.field_name, extracted.state.value,
                            extracted.raw_value, extracted.value_type,
                            extracted.confidence, extracted.extractor_id,
                            extracted.extractor_version, extracted.schema_version,
                        ),
                    )
                    if field.normalized is not None:
                        normalized = field.normalized
                        cursor.execute(
                            """INSERT INTO processing.normalized_value
                               (result_id,result_version,field_ordinal,normalized_value,
                                value_type,normalizer_id,normalizer_version)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (
                                result.result_id, result.result_version, field_ordinal,
                                json.dumps(normalized.value, separators=(",", ":")),
                                normalized.value_type, normalized.normalizer_id,
                                normalized.normalizer_version,
                            ),
                        )
                    for link_ordinal, evidence in enumerate(extracted.evidence):
                        cursor.execute(
                            """INSERT INTO processing.extracted_field_evidence
                               (result_id,result_version,field_ordinal,evidence_ordinal,
                                link_ordinal)
                               VALUES (%s,%s,%s,%s,%s)""",
                            (
                                result.result_id, result.result_version, field_ordinal,
                                evidence_ordinal(evidence), link_ordinal,
                            ),
                        )

                cursor.execute(
                    """UPDATE processing.processing_claim
                       SET status='COMPLETED', completed_at=%s, failure_code=NULL
                       WHERE message_id=%s
                         AND claim_generation=%s
                         AND status='CLAIMED'
                         AND lease_until>%s""",
                    (completed_at, message_id, expected_generation, completed_at),
                )
                if cursor.rowcount != 1:
                    raise ProcessingFinalizationRejected("CLAIM_OWNERSHIP_LOST")
