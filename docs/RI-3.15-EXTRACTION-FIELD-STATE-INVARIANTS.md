# RI-3.15 — Extraction Field-State Invariants

Field-state invariants are enforced by the immutable ExtractedField domain object rather than only by application orchestration.

- PRESENT requires an observed raw value and evidence.
- MISSING permits neither a raw value nor evidence.
- EXPLICIT_NULL requires the observed null marker as raw value plus evidence.
- INVALID requires the uninterpretable/invalid raw value plus evidence.

This prevents invalid field objects from being created through alternate application paths and preserves the distinction between absence, an explicit null marker, and an observed value that cannot be accepted.

Normalization remains downstream and only processes PRESENT fields.
