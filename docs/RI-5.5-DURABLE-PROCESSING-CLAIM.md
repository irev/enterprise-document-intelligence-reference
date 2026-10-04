# RI-5.5 — Durable Processing Claim Ownership

RI-5.5 introduced the durable PostgreSQL processing-claim record used by the at-least-once consumer.

A claim records processing ownership, lease expiry, and a monotonically advancing claim generation. Completion/failure from stale generations is rejected so a previous worker cannot publish terminal state after ownership has moved.

Later milestones strengthen this ownership model with atomic reclaim (RI-5.6), lease-aware reclaim (RI-5.7), finalization fencing (RI-5.8), observation identity dispatch (RI-5.9), and lease renewal (RI-5.12).

This page records the historical milestone boundary rather than redefining the current processing contract.
