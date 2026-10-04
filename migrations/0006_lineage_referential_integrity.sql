-- RI-5.10: database-enforced lineage scope and digest integrity.
--
-- Child rows must not combine an observation/document with a different
-- tenant/application scope. Processing runs must also bind the digest of the
-- exact observation they reference.

ALTER TABLE ingestion.document
    ADD CONSTRAINT document_scope_unique
    UNIQUE (document_id, tenant_id, application_id);

ALTER TABLE ingestion.source_observation
    ADD CONSTRAINT source_observation_scope_unique
    UNIQUE (observation_id, document_id, tenant_id, application_id);

ALTER TABLE ingestion.source_observation
    ADD CONSTRAINT source_observation_scope_digest_unique
    UNIQUE (observation_id, document_id, tenant_id, application_id, sha256);

ALTER TABLE ingestion.source_observation
    DROP CONSTRAINT source_observation_document_id_fkey;

ALTER TABLE ingestion.source_observation
    ADD CONSTRAINT source_observation_document_scope_fk
    FOREIGN KEY (document_id, tenant_id, application_id)
    REFERENCES ingestion.document(document_id, tenant_id, application_id);

ALTER TABLE ingestion.source_reference
    DROP CONSTRAINT source_reference_document_id_fkey;

ALTER TABLE ingestion.source_reference
    ADD CONSTRAINT source_reference_document_scope_fk
    FOREIGN KEY (document_id, tenant_id, application_id)
    REFERENCES ingestion.document(document_id, tenant_id, application_id);

ALTER TABLE ingestion.source_acquisition
    DROP CONSTRAINT source_acquisition_document_id_fkey;

ALTER TABLE ingestion.source_acquisition
    DROP CONSTRAINT source_acquisition_observation_id_fkey;

ALTER TABLE ingestion.source_acquisition
    ADD CONSTRAINT source_acquisition_document_scope_fk
    FOREIGN KEY (document_id, tenant_id, application_id)
    REFERENCES ingestion.document(document_id, tenant_id, application_id);

ALTER TABLE ingestion.source_acquisition
    ADD CONSTRAINT source_acquisition_observation_scope_fk
    FOREIGN KEY (observation_id, document_id, tenant_id, application_id)
    REFERENCES ingestion.source_observation(
        observation_id, document_id, tenant_id, application_id
    );

ALTER TABLE processing.processing_run
    DROP CONSTRAINT processing_run_document_id_fkey;

ALTER TABLE processing.processing_run
    DROP CONSTRAINT processing_run_observation_id_fkey;

ALTER TABLE processing.processing_run
    ADD CONSTRAINT processing_run_document_scope_fk
    FOREIGN KEY (document_id, tenant_id, application_id)
    REFERENCES ingestion.document(document_id, tenant_id, application_id);

ALTER TABLE processing.processing_run
    ADD CONSTRAINT processing_run_observation_integrity_fk
    FOREIGN KEY (
        observation_id, document_id, tenant_id, application_id, observation_sha256
    )
    REFERENCES ingestion.source_observation(
        observation_id, document_id, tenant_id, application_id, sha256
    );

ALTER TABLE integration.outbox_message
    DROP CONSTRAINT outbox_observation_fk;

ALTER TABLE integration.outbox_message
    ADD CONSTRAINT outbox_observation_scope_fk
    FOREIGN KEY (observation_id, tenant_id, application_id)
    REFERENCES ingestion.source_observation(observation_id, tenant_id, application_id);

ALTER TABLE processing.processing_claim
    DROP CONSTRAINT processing_claim_observation_fk;

ALTER TABLE processing.processing_claim
    ADD CONSTRAINT processing_claim_observation_scope_fk
    FOREIGN KEY (observation_id, tenant_id, application_id)
    REFERENCES ingestion.source_observation(observation_id, tenant_id, application_id);
