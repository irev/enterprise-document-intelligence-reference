import os
from datetime import UTC, datetime

import pytest

from edi_reference.adapters.postgresql_inbound import PostgreSqlInboundStore
from edi_reference.domain.inbound import InboundRecord, InboundStatus
from edi_reference.domain.outbox import OutboxMessage

DSN = os.getenv("EDI_TEST_POSTGRES_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="EDI_TEST_POSTGRES_DSN not configured")


def connect():
    import psycopg
    return psycopg.connect(DSN)


def seed_application():
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO control_plane.tenant (tenant_id) VALUES ('atomic-tenant') ON CONFLICT DO NOTHING")
            cursor.execute(
                """INSERT INTO control_plane.application (tenant_id, application_id)
                   VALUES ('atomic-tenant','atomic-app') ON CONFLICT DO NOTHING"""
            )


def record(status=InboundStatus.ACQUIRING):
    now = datetime.now(UTC)
    return InboundRecord(
        "inbound-atomic", "atomic-tenant", "atomic-app", "corr", "req", "idem",
        "a" * 64, "UPLOAD", status, now, now,
        "b" * 64 if status is InboundStatus.ACCEPTED else None,
    )


def message():
    now = datetime.now(UTC)
    return OutboxMessage(
        "message-atomic", "atomic-tenant", "atomic-app", "corr", "inbound-atomic",
        "PROCESS_DOCUMENT", "sha256:" + "b" * 64, now,
    )


def test_acceptance_and_outbox_commit_atomically():
    seed_application()
    store = PostgreSqlInboundStore(connect)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM integration.outbox_message WHERE aggregate_id='inbound-atomic'")
            cursor.execute("DELETE FROM ingestion.inbound_request WHERE inbound_id='inbound-atomic'")
    store.save(record())
    store.accept_and_enqueue(record(InboundStatus.ACCEPTED), message())

    persisted = store.get_by_idempotency("atomic-tenant", "atomic-app", "idem")
    assert persisted.status is InboundStatus.ACCEPTED
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT status FROM integration.outbox_message WHERE message_id='message-atomic'")
            assert cursor.fetchone() == ("PENDING",)


def test_failed_outbox_insert_rolls_back_acceptance():
    seed_application()
    store = PostgreSqlInboundStore(connect)
    with connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM integration.outbox_message WHERE aggregate_id='inbound-atomic'")
            cursor.execute("DELETE FROM ingestion.inbound_request WHERE inbound_id='inbound-atomic'")
    store.save(record())

    # Duplicate message_id makes the outbox INSERT fail after the inbound UPDATE.
    first = message()
    store.accept_and_enqueue(record(InboundStatus.ACCEPTED), first)
    # Restore ACQUIRING while keeping the committed outbox row to create a
    # database-level uniqueness failure inside the next atomic transaction.
    store.save(record(InboundStatus.ACQUIRING))
    duplicate = OutboxMessage(
        first.message_id, "atomic-tenant", "atomic-app", "corr", "inbound-atomic",
        "PROCESS_DOCUMENT", "sha256:" + "b" * 64, datetime.now(UTC),
    )
    with pytest.raises(Exception):
        store.accept_and_enqueue(record(InboundStatus.ACCEPTED), duplicate)

    persisted = store.get_by_idempotency("atomic-tenant", "atomic-app", "idem")
    assert persisted.status is InboundStatus.ACQUIRING
