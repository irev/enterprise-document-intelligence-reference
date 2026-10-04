# RI-1.9 — Durable Source Acquisition

A source acquisition attempt is distinct from a source observation.

Each fetch/upload/connector attempt receives an immutable acquisition identity and status. Successful acquisitions reference the observation produced or reused by that attempt. Multiple acquisitions MAY reference the same observation when reacquired bytes are unchanged.

This preserves the lineage:

SourceReference → SourceAcquisition → SourceObservation → ProcessingRun → Result

An unsuccessful acquisition MUST NOT reference an observation. A successful acquisition MUST reference one.

The in-memory repository is a reference contract only. Production persistence must enforce immutable acquisition identity and tenant/application scope transactionally.

This milestone intentionally does not yet orchestrate REPROCESS, REFETCH or REFETCH_AND_REPROCESS. That orchestration is the next layer and must use these durable records rather than infer acquisition history from processing results.
