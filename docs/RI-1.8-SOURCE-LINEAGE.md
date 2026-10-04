# RI-1.8 — Durable Source Lineage

## Objective

Bind every processing run to the exact source observation it processed and prevent tenant/application scope confusion during reprocess/refetch operations.

## Lineage

```text
Document
  -> SourceObservation v1 (SHA A)
       -> ProcessingRun 1
       -> ProcessingRun 2 (REPROCESS, same observation)

  -> SourceObservation v2 (SHA B)
       -> ProcessingRun 3 (REFETCH_AND_REPROCESS)
```

A processing run records both `observation_id` and the observed SHA-256. Historical runs are never silently rebound when an external source changes.

## Scope authorization

Observation identifiers are not capabilities. Possession or guessing of an `observation_id` grants no access.

Every operation checks tenant and application scope before binding, reprocessing or refetching. Cross-scope failures use a stable non-disclosing access-denied code.

Production repositories must also enforce tenant boundaries in queries and uniqueness constraints; application-layer checks are defense in depth, not the sole isolation mechanism.

## Retry semantics

- REPROCESS: the reacquired digest must equal the targeted observation digest; otherwise `SOURCE_CHANGED`.
- REFETCH: unchanged digest reuses the logical observation while acquisition history remains separately auditable.
- Changed digest creates or resolves a distinct observation for the same logical document.
- REFETCH_AND_REPROCESS is represented by registering/resolving the new observation and then creating a new processing-run binding.

## Security

Content digests are scoped metadata and must not be exposed as a global cross-tenant lookup oracle.

External source version values are informational provenance; they do not override content identity.

Historical observation/result metadata is immutable. Source deletion or unavailability does not rewrite prior lineage.
