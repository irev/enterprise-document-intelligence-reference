-- RI-5.0: PostgreSQL control-plane foundation.
-- Reference implementation only; not a normative platform storage layout.

CREATE SCHEMA IF NOT EXISTS control_plane;

CREATE TABLE control_plane.tenant (
    tenant_id text PRIMARY KEY,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE control_plane.application (
    tenant_id text NOT NULL REFERENCES control_plane.tenant(tenant_id),
    application_id text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, application_id)
);

CREATE TABLE control_plane.provider_configuration (
    provider_id text PRIMARY KEY,
    provider_version text NOT NULL,
    config_version text NOT NULL,
    enabled boolean NOT NULL,
    deployment_zone text NOT NULL,
    engine_ref text NOT NULL,
    secret_ref text,
    endpoint_ref text,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (provider_id <> ''),
    CHECK (provider_version <> ''),
    CHECK (config_version <> ''),
    CHECK (deployment_zone <> ''),
    CHECK (engine_ref <> ''),
    CHECK (secret_ref IS NULL OR secret_ref <> ''),
    CHECK (endpoint_ref IS NULL OR endpoint_ref <> '')
);

CREATE TABLE control_plane.provider_tenant_authorization (
    provider_id text NOT NULL REFERENCES control_plane.provider_configuration(provider_id),
    tenant_id text NOT NULL REFERENCES control_plane.tenant(tenant_id),
    authorized boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (provider_id, tenant_id)
);

CREATE TABLE control_plane.provider_application_authorization (
    provider_id text NOT NULL,
    tenant_id text NOT NULL,
    application_id text NOT NULL,
    authorized boolean NOT NULL DEFAULT true,
    updated_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (provider_id, tenant_id, application_id),
    FOREIGN KEY (provider_id) REFERENCES control_plane.provider_configuration(provider_id),
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id)
);

CREATE TABLE control_plane.execution_policy_version (
    policy_id text NOT NULL,
    policy_version text NOT NULL,
    policy_document jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (policy_id, policy_version),
    CHECK (jsonb_typeof(policy_document) = 'object')
);

CREATE TABLE control_plane.configuration_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    occurred_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    actor_id text NOT NULL,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (actor_id <> ''),
    CHECK (action <> ''),
    CHECK (object_type <> ''),
    CHECK (object_id <> ''),
    CHECK (jsonb_typeof(details) = 'object')
);
