-- RI-5.3: durable document/source/acquisition/observation/processing lineage.

CREATE TABLE ingestion.document (
    document_id text PRIMARY KEY,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    created_at timestamptz NOT NULL,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id)
);

CREATE TABLE ingestion.source_reference (
    source_reference_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES ingestion.document(document_id),
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    method text NOT NULL,
    resource_locator_ref text,
    connector_id text,
    external_version text,
    expected_sha256 text,
    created_at timestamptz NOT NULL,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (method IN ('UPLOAD','SIGNED_URL','CONNECTOR')),
    CHECK (expected_sha256 IS NULL OR expected_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE TABLE ingestion.source_observation (
    observation_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES ingestion.document(document_id),
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    sha256 text NOT NULL,
    byte_length bigint NOT NULL,
    detected_media_type text NOT NULL,
    observed_at timestamptz NOT NULL,
    external_version text,
    UNIQUE (tenant_id, application_id, document_id, sha256),
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (byte_length >= 0)
);

CREATE TABLE ingestion.source_acquisition (
    acquisition_id text PRIMARY KEY,
    source_reference_id text REFERENCES ingestion.source_reference(source_reference_id),
    document_id text NOT NULL REFERENCES ingestion.document(document_id),
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    method text NOT NULL,
    status text NOT NULL,
    acquired_at timestamptz NOT NULL,
    observation_id text REFERENCES ingestion.source_observation(observation_id),
    failure_code text,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (method IN ('UPLOAD','SIGNED_URL','CONNECTOR')),
    CHECK (status IN ('ACQUIRED','REJECTED','UNSUPPORTED','FAILED')),
    CHECK (
      (status = 'ACQUIRED' AND observation_id IS NOT NULL)
      OR (status <> 'ACQUIRED' AND observation_id IS NULL)
    )
);

CREATE SCHEMA IF NOT EXISTS processing;

CREATE TABLE processing.processing_run (
    processing_run_id text PRIMARY KEY,
    document_id text NOT NULL REFERENCES ingestion.document(document_id),
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    observation_id text NOT NULL REFERENCES ingestion.source_observation(observation_id),
    observation_sha256 text NOT NULL,
    created_at timestamptz NOT NULL,
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (observation_sha256 ~ '^[0-9a-f]{64}$')
);
