"""PostgreSQL persistence for immutable result classification."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.classification import ClassificationCandidate, ClassificationPrediction


class PostgreSqlClassificationResultRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def save(
        self,
        result_id: str,
        result_version: str,
        prediction: ClassificationPrediction,
    ) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.classification_result
                       (result_id, result_version, document_type, confidence,
                        model_id, model_version, taxonomy_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        result_id,
                        result_version,
                        prediction.document_type,
                        prediction.confidence,
                        prediction.model_id,
                        prediction.model_version,
                        prediction.taxonomy_version,
                    ),
                )
                for ordinal, alternative in enumerate(prediction.alternatives):
                    cursor.execute(
                        """INSERT INTO processing.classification_alternative
                           (result_id, result_version, alternative_ordinal,
                            document_type, confidence)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (
                            result_id,
                            result_version,
                            ordinal,
                            alternative.document_type,
                            alternative.confidence,
                        ),
                    )

    def get(
        self, result_id: str, result_version: str
    ) -> ClassificationPrediction | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT document_type, confidence, model_id,
                              model_version, taxonomy_version
                       FROM processing.classification_result
                       WHERE result_id=%s AND result_version=%s""",
                    (result_id, result_version),
                )
                root = cursor.fetchone()
                if root is None:
                    return None
                cursor.execute(
                    """SELECT document_type, confidence
                       FROM processing.classification_alternative
                       WHERE result_id=%s AND result_version=%s
                       ORDER BY alternative_ordinal""",
                    (result_id, result_version),
                )
                alternatives = tuple(
                    ClassificationCandidate(row[0], row[1])
                    for row in cursor.fetchall()
                )
        return ClassificationPrediction(
            document_type=root[0],
            confidence=root[1],
            model_id=root[2],
            model_version=root[3],
            taxonomy_version=root[4],
            evidence=(),
            alternatives=alternatives,
        )
