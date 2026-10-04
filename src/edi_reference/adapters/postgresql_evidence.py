"""PostgreSQL persistence for immutable result evidence references."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.evidence import EvidenceKind, EvidenceReference


class PostgreSqlEvidenceRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save_result_evidence(
        self,
        result_id: str,
        result_version: str,
        classification: tuple[EvidenceReference, ...],
        fields: tuple[tuple[EvidenceReference, ...], ...],
    ) -> None:
        evidence_ordinals: dict[EvidenceReference, int] = {}

        def ordinal_for(evidence: EvidenceReference) -> int:
            ordinal = evidence_ordinals.get(evidence)
            if ordinal is not None:
                return ordinal
            ordinal = len(evidence_ordinals)
            evidence_ordinals[evidence] = ordinal
            return ordinal

        for evidence in classification:
            ordinal_for(evidence)
        for field_evidence in fields:
            for evidence in field_evidence:
                ordinal_for(evidence)

        with self._connect() as connection:
            with connection.cursor() as cursor:
                for evidence, ordinal in evidence_ordinals.items():
                    bbox = evidence.bbox
                    cursor.execute(
                        """INSERT INTO processing.evidence_reference
                           (result_id, result_version, evidence_ordinal,
                            observation_id, observation_sha256, page_number, kind,
                            block_id, table_row, table_column, bbox_x0, bbox_y0,
                            bbox_x1, bbox_y1, text_quote)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            result_id, result_version, ordinal,
                            evidence.observation_id, evidence.observation_sha256,
                            evidence.page_number, evidence.kind.value,
                            evidence.block_id, evidence.row, evidence.column,
                            None if bbox is None else bbox.x0,
                            None if bbox is None else bbox.y0,
                            None if bbox is None else bbox.x1,
                            None if bbox is None else bbox.y1,
                            evidence.text_quote,
                        ),
                    )
                for link_ordinal, evidence in enumerate(classification):
                    cursor.execute(
                        """INSERT INTO processing.classification_evidence
                           (result_id,result_version,evidence_ordinal,link_ordinal)
                           VALUES (%s,%s,%s,%s)""",
                        (result_id, result_version, ordinal_for(evidence), link_ordinal),
                    )
                for field_ordinal, field_evidence in enumerate(fields):
                    for link_ordinal, evidence in enumerate(field_evidence):
                        cursor.execute(
                            """INSERT INTO processing.extracted_field_evidence
                               (result_id,result_version,field_ordinal,
                                evidence_ordinal,link_ordinal)
                               VALUES (%s,%s,%s,%s,%s)""",
                            (
                                result_id, result_version, field_ordinal,
                                ordinal_for(evidence), link_ordinal,
                            ),
                        )

    def list_classification(
        self, result_id: str, result_version: str
    ) -> tuple[EvidenceReference, ...]:
        return self._list_linked(
            result_id, result_version, "classification_evidence", None
        )

    def list_field(
        self, result_id: str, result_version: str, field_ordinal: int
    ) -> tuple[EvidenceReference, ...]:
        return self._list_linked(
            result_id, result_version, "extracted_field_evidence", field_ordinal
        )

    def _list_linked(
        self,
        result_id: str,
        result_version: str,
        link_table: str,
        field_ordinal: int | None,
    ) -> tuple[EvidenceReference, ...]:
        field_filter = ""
        parameters: tuple[Any, ...] = (result_id, result_version)
        if field_ordinal is not None:
            field_filter = " AND link.field_ordinal=%s"
            parameters += (field_ordinal,)
        query = f"""SELECT e.observation_id, e.observation_sha256, e.page_number,
                           e.kind, e.block_id, e.table_row, e.table_column,
                           e.bbox_x0, e.bbox_y0, e.bbox_x1, e.bbox_y1,
                           e.text_quote
                    FROM processing.{link_table} link
                    JOIN processing.evidence_reference e
                      ON e.result_id=link.result_id
                     AND e.result_version=link.result_version
                     AND e.evidence_ordinal=link.evidence_ordinal
                    WHERE link.result_id=%s AND link.result_version=%s
                    {field_filter}
                    ORDER BY link.link_ordinal"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, parameters)
                rows = cursor.fetchall()

        from edi_reference.domain.document_structure import BoundingBox

        result = []
        for row in rows:
            bbox = None
            if row[7] is not None:
                bbox = BoundingBox(row[7], row[8], row[9], row[10])
            result.append(
                EvidenceReference(
                    observation_id=row[0],
                    observation_sha256=row[1],
                    page_number=row[2],
                    kind=EvidenceKind(row[3]),
                    block_id=row[4],
                    row=row[5],
                    column=row[6],
                    bbox=bbox,
                    text_quote=row[11],
                )
            )
        return tuple(result)
