"""Outbox publishing boundary.

Production adapters must atomically persist business state and the outbox row.
Publishing is at-least-once; consumers therefore require message-id deduplication.
"""

from dataclasses import replace
from typing import Protocol

from edi_reference.domain.ingestion import Clock
from edi_reference.domain.outbox import OutboxMessage, OutboxStatus


class OutboxRepository(Protocol):
    def pending(self, limit: int) -> list[OutboxMessage]: ...
    def mark(self, message: OutboxMessage) -> None: ...


class MessagePublisher(Protocol):
    def publish(self, message: OutboxMessage) -> None: ...


def publish_pending(
    *,
    repository: OutboxRepository,
    publisher: MessagePublisher,
    clock: Clock,
    limit: int = 100,
) -> int:
    published = 0
    for message in repository.pending(limit):
        try:
            publisher.publish(message)
        except Exception:
            repository.mark(
                replace(
                    message,
                    attempts=message.attempts + 1,
                    last_error_code="PUBLISH_FAILED",
                )
            )
            continue
        repository.mark(
            replace(
                message,
                status=OutboxStatus.PUBLISHED,
                attempts=message.attempts + 1,
                published_at=clock.now(),
                last_error_code=None,
            )
        )
        published += 1
    return published
