CREATE TABLE processing.human_review (
    review_id text NOT NULL,
    review_version integer NOT NULL,
    result_id text NOT NULL,
    result_version text NOT NULL,
    actor_id text NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (review_id, review_version),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.processing_result(result_id, result_version),
    CHECK (review_id <> ''),
    CHECK (review_version >= 0),
    CHECK (actor_id <> '')
);

CREATE TABLE processing.human_review_action (
    review_id text NOT NULL,
    review_version integer NOT NULL,
    action_ordinal integer NOT NULL,
    action text NOT NULL,
    field_name text,
    value jsonb,
    reason text,
    PRIMARY KEY (review_id, review_version, action_ordinal),
    FOREIGN KEY (review_id, review_version)
        REFERENCES processing.human_review(review_id, review_version),
    CHECK (action_ordinal >= 0),
    CHECK (action IN (
        'CONFIRM',
        'CORRECT',
        'MARK_NOT_PRESENT',
        'MARK_ILLEGIBLE',
        'RECLASSIFY',
        'ESCALATE'
    ))
);
