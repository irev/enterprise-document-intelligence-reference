"""PostgreSQL persistence for extracted fields and normalized values."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from edi_reference.domain.normalization import NormalizedField


@dataclass(frozen=True, slots=True)
class DurableFieldRecord:
    field_name: str
    state: str
    raw_value: str | None
    value_type: str
    confidence: float | None
    extractor_id: str
    extractor_version: str
    schema_version: str
    normalized_value: Any | None
    normalized_value_type: str | None
    normalizer_id: str | None
    normalizer_version: str | None


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
                                normalized.value,
                                normalized.value_type,
                                normalized.normalizer_id,
                                normalized.normalizer_version,
                            ),
                        )

    def list_records(
        self, result_id: str, result_version: str
    ) -> tuple[DurableFieldRecord, ...]:
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
                return tuple(DurableFieldRecord(*row) for row in cursor.fetchall())
