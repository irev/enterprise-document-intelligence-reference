-- RI-5.14E: durable immutable execution-plan snapshot per processing run.

CREATE TABLE processing.execution_plan (
    processing_run_id text PRIMARY KEY
        REFERENCES processing.processing_run(processing_run_id),
    profile_id text NOT NULL,
    profile_version text NOT NULL,
    policy_id text NOT NULL,
    policy_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (profile_id, profile_version)
        REFERENCES control_plane.processing_profile_version(profile_id, profile_version),
    FOREIGN KEY (policy_id, policy_version)
        REFERENCES control_plane.execution_policy_version(policy_id, policy_version),
    CHECK (profile_id <> ''),
    CHECK (profile_version <> ''),
    CHECK (policy_id <> ''),
    CHECK (policy_version <> '')
);

CREATE TABLE processing.execution_plan_step (
    processing_run_id text NOT NULL
        REFERENCES processing.execution_plan(processing_run_id) ON DELETE CASCADE,
    step_ordinal integer NOT NULL,
    capability text NOT NULL,
    provider_id text NOT NULL,
    provider_version text NOT NULL,
    execution_class text NOT NULL,
    selection_reason text NOT NULL,
    PRIMARY KEY (processing_run_id, step_ordinal),
    UNIQUE (processing_run_id, capability),
    CHECK (step_ordinal >= 0),
    CHECK (capability IN ('TEXT_EXTRACTION','LAYOUT','CLASSIFICATION','FIELD_EXTRACTION','VALIDATION')),
    CHECK (provider_id <> ''),
    CHECK (provider_version <> ''),
    CHECK (execution_class IN ('DETERMINISTIC','OCR','LOCAL_MODEL','REMOTE_MODEL','HUMAN')),
    CHECK (selection_reason <> '')
);
