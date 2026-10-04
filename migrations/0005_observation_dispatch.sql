-- RI-5.9: processing dispatch is bound to durable observation identity.
--
-- SHA-256 remains an integrity attribute. It is not the processing identity.

ALTER TABLE integration.outbox_message
    ADD COLUMN observation_id text;

ALTER TABLE processing.processing_claim
    ADD COLUMN observation_id text;

ALTER TABLE integration.outbox_message
    ADD CONSTRAINT outbox_observation_fk
    FOREIGN KEY (observation_id)
    REFERENCES ingestion.source_observation(observation_id);

ALTER TABLE processing.processing_claim
    ADD CONSTRAINT processing_claim_observation_fk
    FOREIGN KEY (observation_id)
    REFERENCES ingestion.source_observation(observation_id);

CREATE INDEX outbox_observation_idx
    ON integration.outbox_message (observation_id)
    WHERE observation_id IS NOT NULL;

CREATE INDEX processing_claim_observation_idx
    ON processing.processing_claim (observation_id)
    WHERE observation_id IS NOT NULL;
