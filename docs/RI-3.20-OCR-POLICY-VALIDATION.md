# RI-3.20 — OCR Decision Policy Validation

OCR routing thresholds are configuration and therefore part of the trusted control plane. Invalid threshold values must fail when the policy is constructed rather than producing undefined routing behavior later.

The reference implementation now validates character thresholds, text/image coverage thresholds, and the uncertainty margin. Coverage and margin values are constrained to the normalized 0..1 domain and the character threshold cannot be negative.

This keeps OCR routing deterministic and fail-closed before a real OCR provider is introduced.
