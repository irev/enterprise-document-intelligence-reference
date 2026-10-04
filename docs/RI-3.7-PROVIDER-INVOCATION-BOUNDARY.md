# RI-3.7 — Provider Invocation Boundary

Concrete OCR/model providers remain outside the core. This boundary validates the selected provider against the versioned execution policy immediately before invocation.

It enforces provider identity/version, capability, execution class, data-egress permission, input/output limits and stable sanitized failure codes. Provider exception text is not propagated as a platform failure contract.

The adapter receives an explicit timeout/resource contract. A production adapter is responsible for enforcing the timeout and terminating/cancelling work where supported; the core maps timeout failures to a stable code.

Credentials are intentionally absent from invocation requests and canonical results. Provider adapters obtain credentials from deployment configuration or a secret facility, never from document content.

This layer does not choose fallback providers. A failed invocation becomes an explicit failed execution attempt; RI-3.6 performs a separate policy-governed fallback decision.
