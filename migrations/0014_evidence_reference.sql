-- RI-5.19: durable evidence references for immutable result claims.
--
-- Evidence is stored once per result version and linked to the claims that use
-- it. Exact observation+digest lineage is enforced against the parent result.

ALTER TABLE processing.processing_result
    ADD CONSTRAINT processing_result_evidence_lineage_unique
    UNIQUE (result_id, result_version, observation_id, observation_sha256);

CREATE TABLE processing.evidence_reference (
    result_id text NOT NULL,
    result_version text NOT NULL,
    evidence_ordinal integer NOT NULL,
    observation_id text NOT NULL,
    observation_sha256 text NOT NULL,
    page_number integer NOT NULL,
    kind text NOT NULL,
    block_id text,
    table_row integer,
    table_column integer,
    bbox_x0 double precision,
    bbox_y0 double precision,
    bbox_x1 double precision,
    bbox_y1 double precision,
    text_quote text,
    PRIMARY KEY (result_id, result_version, evidence_ordinal),
    FOREIGN KEY (result_id, result_version, observation_id, observation_sha256)
        REFERENCES processing.processing_result(
            result_id, result_version, observation_id, observation_sha256
        ),
    CHECK (evidence_ordinal >= 0),
    CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (page_number >= 1),
    CHECK (kind IN ('TEXT_BLOCK','TABLE_CELL','REGION')),
    CHECK (
        (kind = 'TEXT_BLOCK' AND block_id IS NOT NULL)
        OR (kind = 'TABLE_CELL' AND block_id IS NOT NULL
            AND table_row IS NOT NULL AND table_column IS NOT NULL)
        OR (kind = 'REGION' AND bbox_x0 IS NOT NULL AND bbox_y0 IS NOT NULL
            AND bbox_x1 IS NOT NULL AND bbox_y1 IS NOT NULL)
    )
);

CREATE TABLE processing.classification_evidence (
    result_id text NOT NULL,
    result_version text NOT NULL,
    evidence_ordinal integer NOT NULL,
    link_ordinal integer NOT NULL,
    PRIMARY KEY (result_id, result_version, link_ordinal),
    UNIQUE (result_id, result_version, evidence_ordinal),
    FOREIGN KEY (result_id, result_version)
        REFERENCES processing.classification_result(result_id, result_version)
        ON DELETE CASCADE,
    FOREIGN KEY (result_id, result_version, evidence_ordinal)
        REFERENCES processing.evidence_reference(
            result_id, result_version, evidence_ordinal
        ) ON DELETE CASCADE,
    CHECK (link_ordinal >= 0)
);

CREATE TABLE processing.extracted_field_evidence (
    result_id text NOT NULL,
    result_version text NOT NULL,
    field_ordinal integer NOT NULL,
    evidence_ordinal integer NOT NULL,
    link_ordinal integer NOT NULL,
    PRIMARY KEY (result_id, result_version, field_ordinal, link_ordinal),
    UNIQUE (result_id, result_version, field_ordinal, evidence_ordinal),
    FOREIGN KEY (result_id, result_version, field_ordinal)
        REFERENCES processing.extracted_field(
            result_id, result_version, field_ordinal
        ) ON DELETE CASCADE,
    FOREIGN KEY (result_id, result_version, evidence_ordinal)
        REFERENCES processing.evidence_reference(
            result_id, result_version, evidence_ordinal
        ) ON DELETE CASCADE,
    CHECK (link_ordinal >= 0)
);
