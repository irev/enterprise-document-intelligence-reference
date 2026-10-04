# RI-5.3 — Durable Source Lineage

RI-5.3 introduced durable document, source-reference, source-observation, source-acquisition, and processing-run lineage records in PostgreSQL.

The milestone established the durable relationship:

```text
Document -> SourceObservation -> ProcessingRun
         -> SourceReference
         -> SourceAcquisition
```

A processing run binds the exact `observation_id` and its SHA-256 integrity attribute. Later milestones strengthen acquisition behavior and referential integrity; see RI-5.4, RI-5.9, RI-5.10, and RI-5.11.

This page records the historical milestone boundary; it does not supersede those later invariants.
