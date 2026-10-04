# RI-5.10 — Lineage Referential Integrity

Lineage scope and observation integrity are database invariants, not application conventions.

RI-5.10 strengthens PostgreSQL relationships so a child row cannot combine a document or observation identity with a different tenant/application scope. Processing runs additionally bind the digest of the exact observation they reference.

## Enforced relationships

- source observation -> document + tenant + application
- source reference -> document + tenant + application
- source acquisition -> document + tenant + application
- source acquisition -> observation + document + tenant + application
- processing run -> document + tenant + application
- processing run -> observation + document + tenant + application + observation digest
- processing outbox -> observation + tenant + application
- processing claim -> observation + tenant + application

These constraints complement application authorization. They prevent invalid lineage from being persisted even when a defective adapter, maintenance script, or direct SQL write bypasses normal application validation.

## Integrity properties

An observation cannot be attached to a document owned by another tenant or application.

A processing run cannot claim that an observation belongs to another document or scope, and cannot persist a digest that differs from the referenced observation.

Dispatch and processing ownership cannot reference an observation from another tenant/application scope.

## Migration policy

RI-5.10 is additive migration `0006_lineage_referential_integrity.sql`. Earlier migrations remain unchanged.

The composite uniqueness constraints introduced by this migration are relational candidate keys used to support scope-preserving foreign keys. They do not change the domain rule that `observation_id` is the authoritative observation identity and SHA-256 is an integrity attribute rather than an observation identity.

## Verification

PostgreSQL integration tests include negative cases for:

- cross-tenant document/observation references;
- cross-application document/observation references;
- processing-run document/observation mismatch;
- processing-run observation digest mismatch;
- outbox observation scope mismatch;
- processing-claim observation scope mismatch.
