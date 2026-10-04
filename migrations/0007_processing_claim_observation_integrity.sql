-- RI-5.x hardening: processing claims bind the exact observation digest.
--
-- Scope-only binding is insufficient because a claim also carries the
-- observation SHA-256 used by processing. The database must reject a claim
-- whose digest disagrees with the authoritative source observation.

ALTER TABLE ingestion.source_observation
    ADD CONSTRAINT source_observation_identity_scope_digest_unique
    UNIQUE (observation_id, tenant_id, application_id, sha256);

ALTER TABLE processing.processing_claim
    DROP CONSTRAINT processing_claim_observation_scope_fk;

ALTER TABLE processing.processing_claim
    ADD CONSTRAINT processing_claim_observation_integrity_fk
    FOREIGN KEY (observation_id, tenant_id, application_id, observation_sha256)
    REFERENCES ingestion.source_observation(
        observation_id, tenant_id, application_id, sha256
    );
