"""PostgreSQL persistence for extracted fields and normalized values."""

from collections.abc import Callable
from typing import Any

from psycopg.types.json import Jsonb

from edi_reference.domain.extraction import ExtractedField, FieldState
from edi_reference.domain.normalization import NormalizedField, NormalizedValue


class PostgreSqlExtractedFieldRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save(
        self,
        result_id: str,
        result_version: str,
        fields: tuple[NormalizedField, ...],
    ) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for ordinal, field in enumerate(fields):
                    extracted = field.extracted
                    cursor.execute(
                        """INSERT INTO processing.extracted_field
                           (result_id, result_version, field_ordinal, field_name,
                            state, raw_value, value_type, confidence, extractor_id,
                            extractor_version, schema_version)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            result_id,
                            result_version,
                            ordinal,
                            extracted.field_name,
                            extracted.state.value,
                            extracted.raw_value,
                            extracted.value_type,
                            extracted.confidence,
                            extracted.extractor_id,
                            extracted.extractor_version,
                            extracted.schema_version,
                        ),
                    )
                    if field.normalized is not None:
                        normalized = field.normalized
                        cursor.execute(
                            """INSERT INTO processing.normalized_value
                               (result_id, result_version, field_ordinal,
                                normalized_value, value_type, normalizer_id,
                                normalizer_version)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (
                                result_id,
                                result_version,
                                ordinal,
                                Jsonb(normalized.value),
                                normalized.value_type,
                                normalized.normalizer_id,
                                normalized.normalizer_version,
                            ),
                        )

    def list_for_result(
        self, result_id: str, result_version: str
    ) -> tuple[NormalizedField, ...]:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT f.field_name, f.state, f.raw_value, f.value_type,
                              f.confidence, f.extractor_id, f.extractor_version,
                              f.schema_version, n.normalized_value, n.value_type,
                              n.normalizer_id, n.normalizer_version
                       FROM processing.extracted_field f
                       LEFT JOIN processing.normalized_value n
                         ON n.result_id=f.result_id
                        AND n.result_version=f.result_version
                        AND n.field_ordinal=f.field_ordinal
                       WHERE f.result_id=%s AND f.result_version=%s
                       ORDER BY f.field_ordinal""",
                    (result_id, result_version),
                )
                rows = cursor.fetchall()

        fields = []
        for row in rows:
            extracted = ExtractedField(
                field_name=row[0],
                state=FieldState(row[1]),
                raw_value=row[2],
                value_type=row[3],
                confidence=row[4],
                evidence=(),
                extractor_id=row[5],
                extractor_version=row[6],
                schema_version=row[7],
            )
            normalized = None
            if row[8] is not None:
                normalized = NormalizedValue(row[8], row[9], row[10], row[11])
            fields.append(NormalizedField(extracted, normalized))
        return tuple(fields)
