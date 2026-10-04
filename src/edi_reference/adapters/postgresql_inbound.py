"""PostgreSQL inbound repository and atomic acceptance/outbox adapter."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.inbound import InboundRecord, InboundStatus
from edi_reference.domain.outbox import OutboxMessage, OutboxStatus
from edi_reference.domain.lineage import SourceObservation


class PostgreSqlInboundStore:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    @staticmethod
    def _record(row: tuple[Any, ...] | None) -> InboundRecord | None:
        if row is None:
            return None
        return InboundRecord(
            inbound_id=row[0], tenant_id=row[1], application_id=row[2],
            correlation_id=row[3], request_id=row[4], idempotency_key=row[5],
            request_fingerprint=row[6], source_method=row[7],
            status=InboundStatus(row[8]), received_at=row[9], updated_at=row[10],
            observation_sha256=row[11], failure_code=row[12],
        )

    def get_by_idempotency(self, tenant_id: str, application_id: str, key: str) -> InboundRecord | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT inbound_id, tenant_id, application_id, correlation_id,
                              request_id, idempotency_key, request_fingerprint, source_method,
                              status, received_at, updated_at, observation_sha256, failure_code
                       FROM ingestion.inbound_request
                       WHERE tenant_id=%s AND application_id=%s AND idempotency_key=%s""",
                    (tenant_id, application_id, key),
                )
                return self._record(cursor.fetchone())

    def save(self, record: InboundRecord) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ingestion.inbound_request
                       (inbound_id, tenant_id, application_id, correlation_id, request_id,
                        idempotency_key, request_fingerprint, source_method, status,
                        received_at, updated_at, observation_sha256, failure_code)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (inbound_id) DO UPDATE SET
                         status=EXCLUDED.status, updated_at=EXCLUDED.updated_at,
                         observation_sha256=EXCLUDED.observation_sha256,
                         failure_code=EXCLUDED.failure_code""",
                    (
                        record.inbound_id, record.tenant_id, record.application_id,
                        record.correlation_id, record.request_id, record.idempotency_key,
                        record.request_fingerprint, record.source_method, record.status.value,
                        record.received_at, record.updated_at, record.observation_sha256,
                        record.failure_code,
                    ),
                )

    def accept_and_enqueue(
        self, record: InboundRecord, observation: SourceObservation, message: OutboxMessage
    ) -> None:
        if record.status is not InboundStatus.ACCEPTED:
            raise ValueError("ATOMIC_ACCEPTANCE_REQUIRES_ACCEPTED_RECORD")
        if message.status is not OutboxStatus.PENDING:
            raise ValueError("ATOMIC_ACCEPTANCE_REQUIRES_PENDING_MESSAGE")
        if message.aggregate_id != record.inbound_id:
            raise ValueError("OUTBOX_AGGREGATE_MISMATCH")
        if observation.document_id != record.inbound_id:
            raise ValueError("OBSERVATION_DOCUMENT_MISMATCH")
        if (observation.tenant_id, observation.application_id) != (record.tenant_id, record.application_id):
            raise ValueError("OBSERVATION_SCOPE_MISMATCH")
        if observation.sha256.lower() != (record.observation_sha256 or "").lower():
            raise ValueError("OBSERVATION_DIGEST_MISMATCH")
        if message.observation_id != observation.observation_id:
            raise ValueError("OUTBOX_OBSERVATION_MISMATCH")

        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO ingestion.document
                       (document_id, tenant_id, application_id, created_at)
                       VALUES (%s,%s,%s,%s)
                       ON CONFLICT (document_id) DO NOTHING""",
                    (
                        observation.document_id, observation.tenant_id,
                        observation.application_id, observation.observed_at,
                    ),
                )
                cursor.execute(
                    """INSERT INTO ingestion.source_observation
                       (observation_id, document_id, tenant_id, application_id, sha256,
                        byte_length, detected_media_type, observed_at, external_version)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        observation.observation_id, observation.document_id,
                        observation.tenant_id, observation.application_id,
                        observation.sha256, observation.byte_length,
                        observation.detected_media_type, observation.observed_at,
                        observation.external_version,
                    ),
                )

                cursor.execute(
                    """UPDATE ingestion.inbound_request
                       SET status=%s, updated_at=%s, observation_sha256=%s, failure_code=%s
                       WHERE inbound_id=%s AND tenant_id=%s AND application_id=%s""",
                    (
                        record.status.value, record.updated_at, record.observation_sha256,
                        record.failure_code, record.inbound_id, record.tenant_id,
                        record.application_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("INBOUND_RECORD_NOT_FOUND")

                cursor.execute(
                    """INSERT INTO integration.outbox_message
                       (message_id, tenant_id, application_id, correlation_id, aggregate_id,
                        message_type, payload_ref, created_at, status, attempts,
                        published_at, last_error_code, observation_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        message.message_id, message.tenant_id, message.application_id,
                        message.correlation_id, message.aggregate_id, message.message_type,
                        message.payload_ref, message.created_at, message.status.value,
                        message.attempts, message.published_at, message.last_error_code,
                        message.observation_id,
                    ),
                )
