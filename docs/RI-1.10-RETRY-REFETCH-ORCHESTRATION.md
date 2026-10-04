# RI-1.10 — Retry and Refetch Orchestration

The three processing intents now have explicit orchestration semantics.

- REPROCESS targets the existing observation. Reacquired bytes MUST match its digest or the operation fails with SOURCE_CHANGED. A new processing run is bound to the existing observation.
- REFETCH acquires the latest source state and records/reuses the resulting observation, but does not create a processing run.
- REFETCH_AND_REPROCESS performs the refetch semantics and then creates a processing run bound to the resulting observation.

An unchanged refetch reuses the existing observation. A changed refetch creates or reuses a scoped observation with the new digest.

Acquisition itself remains outside this function: the orchestrator consumes validated acquisition facts. This prevents retry semantics from bypassing source security/MIME/size validation.

Production integration must persist the SourceAcquisition for every actual acquisition attempt before/with applying these semantics. Failure to acquire a source leaves the prior observation and completed results unchanged.
