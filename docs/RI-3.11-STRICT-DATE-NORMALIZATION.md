# RI-3.11 — Strict Date Normalization

The reference ISO date normalizer accepts only the canonical calendar-date lexical form `YYYY-MM-DD`.

It deliberately rejects compact dates, non-zero-padded dates, ISO week dates and locale-dependent formats even when a runtime date parser could interpret them.

Normalization is deterministic canonicalization, not date inference. Other accepted source formats require separately identified and versioned normalizers so their interpretation is explicit and testable.
