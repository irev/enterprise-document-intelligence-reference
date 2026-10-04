-- RI-5.14D: durable versioned processing profiles and scoped bindings.
--
-- Execution policy content remains owned by execution_policy_version. A profile
-- references an exact policy version instead of duplicating policy JSON.

CREATE TABLE control_plane.processing_profile_version (
    profile_id text NOT NULL,
    profile_version text NOT NULL,
    policy_id text NOT NULL,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (profile_id, profile_version),
    FOREIGN KEY (policy_id, policy_version)
        REFERENCES control_plane.execution_policy_version(policy_id, policy_version),
    CHECK (profile_id <> ''),
    CHECK (profile_version <> ''),
    CHECK (policy_id <> ''),
    CHECK (policy_version <> '')
);

CREATE TABLE control_plane.processing_profile_binding (
    tenant_id text NOT NULL REFERENCES control_plane.tenant(tenant_id),
    application_id text,
    profile_id text NOT NULL,
    profile_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id, profile_version)
        REFERENCES control_plane.processing_profile_version(profile_id, profile_version),
    FOREIGN KEY (tenant_id, application_id)
        REFERENCES control_plane.application(tenant_id, application_id),
    CHECK (application_id IS NULL OR application_id <> ''),
    CHECK (profile_id <> ''),
    CHECK (profile_version <> '')
);

CREATE UNIQUE INDEX processing_profile_tenant_default_unique
    ON control_plane.processing_profile_binding (tenant_id)
    WHERE application_id IS NULL;

CREATE UNIQUE INDEX processing_profile_application_unique
    ON control_plane.processing_profile_binding (tenant_id, application_id)
    WHERE application_id IS NOT NULL;
