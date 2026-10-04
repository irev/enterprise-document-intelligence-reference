"""PostgreSQL processing-claim repository with generation fencing."""

from collections.abc import Callable
from typing import Any

from edi_reference.domain.processing import ProcessingClaim, ProcessingClaimStatus


class PostgreSqlProcessingClaimRepository:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    @staticmethod
    def _map(row):
        if row is None:
            return None
        return ProcessingClaim(
            message_id=row[0], processing_run_id=row[1], tenant_id=row[2],
            application_id=row[3], observation_sha256=row[4],
            status=ProcessingClaimStatus(row[5]), claimed_at=row[6],
            lease_until=row[7], claim_generation=row[8], completed_at=row[9],
            failure_code=row[10],
        )

    def get(self, message_id: str) -> ProcessingClaim | None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT message_id, processing_run_id, tenant_id, application_id,
                              observation_sha256, status, claimed_at, lease_until,
                              claim_generation, completed_at, failure_code
                       FROM processing.processing_claim WHERE message_id=%s""",
                    (message_id,),
                )
                return self._map(cursor.fetchone())

    def try_create(self, claim: ProcessingClaim) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO processing.processing_claim
                       (message_id, processing_run_id, tenant_id, application_id,
                        observation_sha256, status, claimed_at, lease_until,
                        claim_generation, completed_at, failure_code)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (message_id) DO NOTHING""",
                    self._params(claim),
                )
                return cursor.rowcount == 1

    def save(self, claim: ProcessingClaim) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE processing.processing_claim SET
                         processing_run_id=%s, tenant_id=%s, application_id=%s,
                         observation_sha256=%s, status=%s, claimed_at=%s,
                         lease_until=%s, claim_generation=%s, completed_at=%s,
                         failure_code=%s
                       WHERE message_id=%s""",
                    (
                        claim.processing_run_id, claim.tenant_id, claim.application_id,
                        claim.observation_sha256, claim.status.value, claim.claimed_at,
                        claim.lease_until, claim.claim_generation, claim.completed_at,
                        claim.failure_code, claim.message_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("PROCESSING_CLAIM_NOT_FOUND")

    def try_reclaim(self, claim: ProcessingClaim, expected_generation: int, *, now) -> bool:
        """Advance an existing claim only if the caller still owns the observed generation."""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE processing.processing_claim SET
                         processing_run_id=%s, tenant_id=%s, application_id=%s,
                         observation_sha256=%s, status=%s, claimed_at=%s,
                         lease_until=%s, claim_generation=%s, completed_at=%s,
                         failure_code=%s
                       WHERE message_id=%s
                         AND claim_generation=%s
                         AND (
                           status = 'FAILED'
                           OR (status = 'CLAIMED' AND lease_until <= %s)
                         )""",
                    (
                        claim.processing_run_id, claim.tenant_id, claim.application_id,
                        claim.observation_sha256, claim.status.value, claim.claimed_at,
                        claim.lease_until, claim.claim_generation, claim.completed_at,
                        claim.failure_code, claim.message_id, expected_generation, now,
                    ),
                )
                return cursor.rowcount == 1

    def save_if_generation(self, claim: ProcessingClaim, expected_generation: int, *, now) -> bool:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """UPDATE processing.processing_claim SET
                         status=%s, claimed_at=%s, lease_until=%s,
                         claim_generation=%s, completed_at=%s, failure_code=%s
                       WHERE message_id=%s AND claim_generation=%s""",
                    (
                        claim.status.value, claim.claimed_at, claim.lease_until,
                        claim.claim_generation, claim.completed_at, claim.failure_code,
                        claim.message_id, expected_generation,
                    ),
                )
                return cursor.rowcount == 1

    @staticmethod
    def _params(claim: ProcessingClaim):
        return (
            claim.message_id, claim.processing_run_id, claim.tenant_id,
            claim.application_id, claim.observation_sha256, claim.status.value,
            claim.claimed_at, claim.lease_until, claim.claim_generation,
            claim.completed_at, claim.failure_code,
        )
