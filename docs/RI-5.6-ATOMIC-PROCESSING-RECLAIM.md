# RI-5.6 — Atomic Processing Claim Reclaim

Processing claim takeover is a compare-and-swap operation.

A worker that observed generation N may reclaim the claim only while the durable row still has generation N. The successful takeover advances the generation. A competing worker attempting the same takeover from the stale generation receives no ownership and must use the current durable claim.

This closes the read-then-write race that exists when reclaim is implemented as separate get and unconditional save operations.

Generation fencing remains required when writing completion or failure after processing. Atomic reclaim establishes ownership; generation-fenced completion prevents stale ownership from publishing a later state.
