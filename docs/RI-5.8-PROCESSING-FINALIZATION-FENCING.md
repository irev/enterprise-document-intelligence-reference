# RI-5.8 — Processing Finalization Lease Fencing

Processing completion and failure are ownership-sensitive writes.

A matching claim generation alone is insufficient to finalize processing. The durable claim MUST still be in CLAIMED state and its lease MUST be active at the time the final state is written.

The reference therefore accepts finalization only when all of these conditions hold atomically:

- message identity matches;
- claim generation matches;
- current durable status is CLAIMED;
- lease has not expired.

This prevents a worker that still holds the latest generation, but has exceeded its lease, from publishing COMPLETED or FAILED before another worker performs a reclaim.

Claim ownership is consequently defined by generation plus a live lease, not by generation alone.


## Processing failure boundary

A processor reports an expected document-level processing failure by raising `ProcessingFailure`. The consumer maps only that explicit failure type to the stable durable code `PROCESSING_FAILED`, subject to the same generation, `CLAIMED`-state, and live-lease finalization fence described above.

Unexpected implementation defects are not document outcomes and MUST propagate rather than being persisted as `PROCESSING_FAILED`. Ownership and lease-control failures likewise remain control-plane failures and MUST NOT be converted into document-processing failure.

Long-running processors use the same failure boundary together with the lease-renewal contract defined in [RI-5.12](RI-5.12-LONG-RUNNING-PROCESSING-SAFETY.md).
