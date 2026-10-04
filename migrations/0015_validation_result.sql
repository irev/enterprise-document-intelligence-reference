-- RI-6.1: durable deterministic validation results and findings.

CREATE TABLE processing.validation_result (
    result_id text NOT NULL,
    result_version text NOT NULL,
    validation_version text NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (result_id, result_version, validation_version),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.processing_result(result_id, result_version),
    CHECK (validation_version <> ''),
    CHECK (status IN ('VALID','REVIEW_REQUIRED','INVALID','UNSUPPORTED'))
);

CREATE TABLE processing.validation_finding (
    result_id text NOT NULL,
    result_version text NOT NULL,
    validation_version text NOT NULL,
    finding_ordinal integer NOT NULL,
    code text NOT NULL,
    severity text NOT NULL,
    source text NOT NULL,
    rule_version text,
    message text,
    documents jsonb NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (result_id,result_version,validation_version,finding_ordinal),
    FOREIGN KEY (result_id,result_version,validation_version)
        REFERENCES processing.validation_result(
            result_id,result_version,validation_version
        ),
    CHECK (finding_ordinal >= 0),
    CHECK (code <> ''),
    CHECK (severity IN ('INFO','WARNING','ERROR','BLOCKING')),
    CHECK (source <> ''),
    CHECK (jsonb_typeof(documents) = 'array')
);
