-- RI-5.15: durable actual execution/fallback attempt history.

CREATE TABLE processing.execution_attempt (
    attempt_id text PRIMARY KEY,
    processing_run_id text NOT NULL
        REFERENCES processing.execution_plan(processing_run_id),
    attempt_ordinal integer NOT NULL,
    capability text NOT NULL,
    provider_id text NOT NULL,
    provider_version text NOT NULL,
    execution_class text NOT NULL,
    status text NOT NULL,
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (processing_run_id, attempt_ordinal),
    CHECK (attempt_id <> ''),
    CHECK (attempt_ordinal >= 0),
    CHECK (capability IN ('TEXT_EXTRACTION','LAYOUT','CLASSIFICATION','FIELD_EXTRACTION','VALIDATION')),
    CHECK (provider_id <> ''),
    CHECK (provider_version <> ''),
    CHECK (execution_class IN ('DETERMINISTIC','OCR','LOCAL_MODEL','REMOTE_MODEL','HUMAN')),
    CHECK (status IN ('SUCCEEDED','FAILED')),
    CHECK (
      (status = 'SUCCEEDED' AND failure_code IS NULL)
      OR (status = 'FAILED' AND failure_code IS NOT NULL AND failure_code <> '')
    )
);
