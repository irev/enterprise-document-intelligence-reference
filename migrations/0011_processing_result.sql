-- RI-5.16: durable immutable processing-result aggregate root.
--
-- Child classification/field/evidence persistence follows in later milestones.
-- This root establishes result identity, version, run ownership and exact source
-- lineage without serializing derived artifacts into an opaque JSON blob.

ALTER TABLE processing.processing_run
    ADD CONSTRAINT processing_run_result_lineage_unique
    UNIQUE (
        processing_run_id, document_id, tenant_id, application_id,
        observation_id, observation_sha256
    );

CREATE TABLE processing.processing_result (
    result_id text NOT NULL,
    result_version text NOT NULL,
    processing_run_id text NOT NULL,
    document_id text NOT NULL,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    observation_id text NOT NULL,
    observation_sha256 text NOT NULL,
    schema_version text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (result_id, result_version),
    UNIQUE (processing_run_id, result_version),
    FOREIGN KEY (
        processing_run_id, document_id, tenant_id, application_id,
        observation_id, observation_sha256
    )
        REFERENCES processing.processing_run(
            processing_run_id, document_id, tenant_id, application_id,
            observation_id, observation_sha256
        ),
    CHECK (result_id <> ''),
    CHECK (result_version <> ''),
    CHECK (schema_version <> ''),
    CHECK (observation_sha256 ~ '^[0-9a-f]{64}$')
);
