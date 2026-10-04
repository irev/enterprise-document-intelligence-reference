from datetime import UTC, datetime

from edi_reference.application.outbox import publish_pending
from edi_reference.domain.outbox import OutboxMessage, OutboxStatus


class FixedClock:
    def now(self):
        return datetime(2026, 10, 4, 10, 0, tzinfo=UTC)


class Repo:
    def __init__(self, message):
        self.message = message

    def pending(self, limit):
        return [self.message] if self.message.status is OutboxStatus.PENDING else []

    def mark(self, message):
        self.message = message


class Publisher:
    def __init__(self, fail=False):
        self.fail = fail
        self.ids = []

    def publish(self, message):
        self.ids.append(message.message_id)
        if self.fail:
            raise RuntimeError("provider detail must not be persisted")


def message():
    return OutboxMessage(
        message_id="msg-1",
        tenant_id="tenant-a",
        application_id="app-a",
        correlation_id="corr-1",
        aggregate_id="inbound-1",
        message_type="PROCESS_DOCUMENT",
        payload_ref="sha256:" + "a" * 64,
        created_at=FixedClock().now(),
    )


def test_successful_publish_marks_message_published() -> None:
    repo = Repo(message())
    assert publish_pending(repository=repo, publisher=Publisher(), clock=FixedClock()) == 1
    assert repo.message.status is OutboxStatus.PUBLISHED
    assert repo.message.attempts == 1


def test_publish_failure_records_stable_code_not_exception_text() -> None:
    repo = Repo(message())
    assert publish_pending(repository=repo, publisher=Publisher(fail=True), clock=FixedClock()) == 0
    assert repo.message.status is OutboxStatus.PENDING
    assert repo.message.attempts == 1
    assert repo.message.last_error_code == "PUBLISH_FAILED"
