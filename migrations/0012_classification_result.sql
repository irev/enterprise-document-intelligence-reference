-- RI-5.17: durable immutable classification output per result version.

CREATE TABLE processing.classification_result (
    result_id text NOT NULL,
    result_version text NOT NULL,
    document_type text NOT NULL,
    confidence double precision NOT NULL,
    model_id text NOT NULL,
    model_version text NOT NULL,
    taxonomy_version text NOT NULL,
    PRIMARY KEY (result_id, result_version),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.processing_result(result_id, result_version)
        ON DELETE CASCADE,
    CHECK (document_type <> ''),
    CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CHECK (model_id <> ''),
    CHECK (model_version <> ''),
    CHECK (taxonomy_version <> '')
);

CREATE TABLE processing.classification_alternative (
    result_id text NOT NULL,
    result_version text NOT NULL,
    alternative_ordinal integer NOT NULL,
    document_type text NOT NULL,
    confidence double precision NOT NULL,
    PRIMARY KEY (result_id, result_version, alternative_ordinal),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.classification_result(result_id, result_version)
        ON DELETE CASCADE,
    CHECK (alternative_ordinal >= 0),
    CHECK (document_type <> ''),
    CHECK (confidence >= 0.0 AND confidence <= 1.0)
);
