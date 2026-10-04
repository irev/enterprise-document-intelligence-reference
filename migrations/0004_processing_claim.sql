-- RI-5.5: durable processing claim lease and generation fencing.

CREATE TABLE processing.processing_claim (
    message_id text PRIMARY KEY REFERENCES integration.outbox_message(message_id),
    processing_run_id text NOT NULL,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    observation_sha256 text NOT NULL,
    status text NOT NULL,
    claimed_at timestamptz NOT NULL,
    lease_until timestamptz NOT NULL,
    claim_generation bigint NOT NULL,
    completed_at timestamptz,
    failure_code text,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (status IN ('CLAIMED','COMPLETED','FAILED')),
    CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (claim_generation >= 1),
    CHECK (lease_until >= claimed_at),
    CHECK ((status = 'COMPLETED' AND completed_at IS NOT NULL) OR status <> 'COMPLETED')
);

CREATE INDEX processing_claim_lease_idx
    ON processing.processing_claim (lease_until, message_id)
    WHERE status = 'CLAIMED';
