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
