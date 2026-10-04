-- RI-5.18: durable extracted fields and deterministic normalized values.
--
-- Raw observed representation is stored separately from normalized JSON.
-- normalized_value is JSONB because the current normalization contract produces
-- canonical JSON-compatible scalar/object values; value_type and normalizer
-- identity preserve interpretation and provenance.

CREATE TABLE processing.extracted_field (
    result_id text NOT NULL,
    result_version text NOT NULL,
    field_ordinal integer NOT NULL,
    field_name text NOT NULL,
    state text NOT NULL,
    raw_value text,
    value_type text NOT NULL,
    confidence double precision,
    extractor_id text NOT NULL,
    extractor_version text NOT NULL,
    schema_version text NOT NULL,
    PRIMARY KEY (result_id, result_version, field_ordinal),
    UNIQUE (result_id, result_version, field_name),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.processing_result(result_id, result_version)
        ON DELETE CASCADE,
    CHECK (field_ordinal >= 0),
    CHECK (field_name <> ''),
    CHECK (state IN ('PRESENT','MISSING','EXPLICIT_NULL','INVALID')),
    CHECK (value_type <> ''),
    CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
    CHECK (extractor_id <> ''),
    CHECK (extractor_version <> ''),
    CHECK (schema_version <> ''),
    CHECK (
      (state = 'MISSING' AND raw_value IS NULL)
      OR (state <> 'MISSING' AND raw_value IS NOT NULL)
    )
);

CREATE TABLE processing.normalized_value (
    result_id text NOT NULL,
    result_version text NOT NULL,
    field_ordinal integer NOT NULL,
    normalized_value jsonb NOT NULL,
    value_type text NOT NULL,
    normalizer_id text NOT NULL,
    normalizer_version text NOT NULL,
    PRIMARY KEY (result_id, result_version, field_ordinal),
    FOREIGN KEY (result_id, result_version, field_ordinal)
        REFERENCES processing.extracted_field(
            result_id, result_version, field_ordinal
        ) ON DELETE CASCADE,
    CHECK (value_type <> ''),
    CHECK (normalizer_id <> ''),
    CHECK (normalizer_version <> '')
);
