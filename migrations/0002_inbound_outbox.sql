-- RI-5.2: durable inbound identity and transactional processing outbox.

CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS integration;

CREATE TABLE ingestion.inbound_request (
    inbound_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    correlation_id text NOT NULL,
    request_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_fingerprint text NOT NULL,
    source_method text NOT NULL,
    status text NOT NULL,
    received_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    observation_sha256 text,
    failure_code text,
    UNIQUE (tenant_id, application_id, idempotency_key),
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (status IN ('RECEIVED','ACQUIRING','ACCEPTED','REJECTED','UNSUPPORTED','FAILED')),
    CHECK (request_fingerprint ~ '^[0-9a-f]{64}$'),
    CHECK (observation_sha256 IS NULL OR observation_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE integration.outbox_message (
    message_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    correlation_id text NOT NULL,
    aggregate_id text NOT NULL REFERENCES ingestion.inbound_request(inbound_id),
    message_type text NOT NULL,
    payload_ref text NOT NULL,
    created_at timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'PENDING',
    attempts integer NOT NULL DEFAULT 0,
    published_at timestamptz,
    last_error_code text,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (status IN ('PENDING','PUBLISHED','DEAD_LETTER')),
    CHECK (attempts >= 0)
);

CREATE INDEX IF NOT EXISTS outbox_pending_created_idx
    ON integration.outbox_message (created_at, message_id)
    WHERE status = 'PENDING';
