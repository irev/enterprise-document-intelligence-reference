# RI-5.7 — Lease-Aware Processing Reclaim

RI-5.7 strengthened atomic claim reclaim so an active `CLAIMED` lease cannot be taken over merely because a worker presents the current generation.

Reclaim is permitted only for a reclaimable durable state: a failed claim or a claimed lease that has expired. Generation comparison and lease/state eligibility are evaluated atomically.

This closes the gap between generation fencing and time-bounded ownership. RI-5.8 subsequently applies the same live-lease requirement to terminal completion/failure, and RI-5.12 adds generation-fenced lease renewal for long-running work.
