# RI-4.9 — Persistence Technology Decision

## Decision

The Python reference implementation will use **PostgreSQL** as its primary durable transactional database when persistence adapters are introduced.

This is a reference-implementation choice, not a requirement of the platform specification.

## Why PostgreSQL

The current reference architecture requires strong transactional behavior for scoped idempotency, atomic inbound acceptance plus outbox insertion, processing lease/fencing compare-and-set operations, provider authorization/configuration changes, immutable result versioning, review concurrency and delivery retry state.

A relational model fits these invariants directly. PostgreSQL provides transactions, unique constraints, foreign keys, row locking, compare-and-set style updates, JSON support for bounded extension data, and mature Python drivers.

SQLite remains suitable for developer experiments but is not the production conformance target. Redis may later be used for cache/coordination optimizations, but MUST NOT become the sole system of record for the durable invariants. Original document binaries and model artifacts are intentionally outside the primary relational database.

## Logical schemas

The initial database is divided by ownership rather than by customer-specific workflow:

- control_plane: tenant, application, provider configuration, provider authorization, execution policy/profile versions;
- ingestion: inbound request, source reference, acquisition, observation;
- processing: processing run, claim/lease/fencing generation, result version/provenance;
- review: review task, decision/correction, concurrency version;
- integration: outbox message, outbound delivery, delivery attempt;
- audit: security/configuration/processing audit events.

Physical PostgreSQL schemas are an implementation option; the logical boundaries are more important than schema names.

## Core relational constraints

The persistence implementation should enforce at database level where possible:
- UNIQUE (tenant_id, application_id, idempotency_key);
- immutable identity for source observations and completed result versions;
- foreign-key lineage from processing runs to source observations;
- monotonic processing claim generation used as fencing token;
- optimistic concurrency/version checks for mutable review state;
- provider authorization scoped by tenant/application;
- transactional creation of accepted inbound state and its processing outbox message.

## Payload placement

PostgreSQL stores metadata, state, provenance and structured results. It does not become the default original-document blob store.

Original documents remain source-owned or live in an authorized object/document repository. Temporary OCR/parser copies are ephemeral. OCR/model artifacts remain in model/runtime storage.

## Secrets

Provider configuration stores only secret references. Secret material itself belongs behind a secret-management adapter.

## Planned adapter stack

The persistence port remains domain/application-facing. PostgreSQL-specific SQL and driver types terminate inside adapters.

The first implementation should prefer explicit SQL migrations and a thin persistence layer over embedding database semantics into domain objects. Driver/ORM choice is deferred until the first adapter slice so it can be evaluated against transaction, locking and async requirements rather than selected prematurely.

## First durable slice

Implement persistence in this order:

1. tenant/application/provider configuration and authorization;
2. inbound request + atomic acceptance/outbox;
3. source observation/acquisition lineage;
4. processing claim with generation fencing;
5. processing result/version provenance;
6. review concurrency;
7. outbound delivery/retry and audit.

The first database-backed vertical test should prove that a provider authorization revocation committed after planning prevents invocation, using current durable control-plane state.
