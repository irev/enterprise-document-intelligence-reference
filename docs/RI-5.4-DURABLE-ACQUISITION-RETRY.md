# RI-5.4 — Durable Acquisition and Retry/Refetch Lineage

The PostgreSQL reference persists source acquisition attempts independently from source observations.

Retry semantics remain explicit:
- REPROCESS verifies the reacquired digest against the selected observation and processes that observation.
- REFETCH records or reuses the observation representing the newly acquired bytes without automatically processing it.
- REFETCH_AND_REPROCESS records or reuses the refetched observation and binds a new processing run to that exact observation.

A processing run is therefore bound to source identity through observation_id, with SHA-256 retained as an integrity attribute. A digest alone is not source identity.

The reference keeps acquisition outcome, observation identity, and processing execution as separate lifecycle facts.
