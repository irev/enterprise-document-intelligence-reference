# RI-3.18 — Provider Execution/Egress Invariants

Provider descriptors now enforce consistency between execution topology and declared data egress.

- REMOTE_MODEL providers must declare APPROVED_EXTERNAL egress.
- Non-remote providers must declare NONE.

This prevents a remote provider from being represented as a no-egress provider and prevents local/OCR/deterministic adapters from silently carrying an external-egress declaration.

Execution policy remains responsible for deciding whether external egress is permitted for a request. The descriptor invariant only makes provider topology truthful and machine-checkable.
