# RI-0.5 — Shared Service Architecture

## Goal

Shape the Python reference implementation as a reusable Document Intelligence service that can serve multiple authorized applications while preserving the specification's tenant, evidence, audit and decision boundaries.

## System context

```text
Consumer App A ----\
Consumer App B -----+--> Document Intelligence Service
Other App ----------/            |
                                 +--> processing pipeline
                                 +--> result API/events/callbacks
                                 +--> operations/control panel
```

The service is not an RFP application. RFP is one consumer/domain profile.

## Identity boundaries

The implementation will keep these identities separate:

```text
tenant_id
application_id
request_id
correlation_id
idempotency_key
document_id
processing_run_id
result_version
external business references
outbound message/delivery identity
```

None is interchangeable merely because values happen to match.

## Logical planes

### Data plane

Handles consumer-facing processing traffic:
- authenticated submission;
- source ingestion;
- lifecycle/status;
- result retrieval;
- review operations where enabled;
- events/callback delivery.

### Control plane

Handles service administration and operations:
- application registration and authorization;
- tenant-scoped configuration;
- integration/subscription configuration;
- processing inspection;
- review queue;
- outbound delivery/retry inspection;
- provider health;
- audit and operational telemetry.

Control-plane authorization is independent of UI visibility.

### Processing plane

Executes document understanding:
- safe parsing/OCR;
- classification;
- extraction;
- normalization;
- deterministic validation;
- evidence/provenance;
- versioned result production.

Provider integrations remain adapters.

## Inbound lifecycle

```text
authenticated application
  -> authorized tenant scope
  -> request/correlation identity
  -> idempotency check
  -> source validation
  -> document + processing identity
  -> accepted processing
```

An inbound monitor is a projection/operational view of these records, not the authoritative business workflow.

## Outbound lifecycle

```text
completed/reviewable result
  -> logical outbound message
  -> authorized subscription/destination
  -> delivery attempt
       -> DELIVERED
       -> RETRY_PENDING
       -> FAILED
```

A callback failure does not change a completed processing result into a processing failure.

## Control panel modules

Initial information architecture:

- Dashboard
- Inbound
- Processing
- Documents
- Review
- Outbound
- Findings
- Applications
- Tenants
- Providers
- Profiles / Policies
- Audit

The panel MUST NOT contain payment approval or other RFP business authorization.

## Security boundaries

- Consumer identity is authenticated independently of payload tenant labels.
- Application-to-tenant access is explicitly authorized.
- Callback destinations are registered configuration; document content cannot choose a destination.
- Integration credentials are secrets and never exposed in results/logs/panel views.
- Raw document access is separately authorized and auditable.
- Private corporate fixtures are prohibited from this repository.

## Implementation sequencing

RI-0.5 defines boundaries but does not require a framework yet.

Next milestones:

1. RI-1: deterministic ingestion and identity.
2. RI-1.5: application authentication/authorization and inbound operational records.
3. RI-2: parser/OCR adapter.
4. RI-3: classification/extraction.
5. RI-4: normalization/validation.
6. RI-4.5: outbound delivery worker and retry semantics.
7. RI-5: review/versioning.
8. RI-5.5: operations/control-panel API and UI.
9. RI-6: bundle/business profiles.

This ordering keeps the service reusable while avoiding premature UI/provider coupling.
