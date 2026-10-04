# RI-3.8 — Provider Adapter Contract and Conformance

Concrete OCR and model integrations implement a minimal provider SPI. The adapter declares a provider descriptor and performs invocation; it does not choose execution policy, fallback, tenant permissions or data-egress rules.

A descriptor binds adapter identity/version to the provider capability declaration. Canonical platform contracts remain independent from provider SDKs.

The first reusable conformance harness verifies descriptor/capability declaration and that an adapter rejects unsupported capabilities without requiring real network/model execution.

Production adapters must additionally satisfy the RI-3.7 invocation boundary: stable provider identity/version, resource limits, cancellation/timeout behavior where supported, sanitized failures and no credentials in canonical request/result objects.

This is intentionally a minimal SPI. Health probing, lifecycle management and provider-specific configuration are control-plane concerns and should not expand the canonical business result contract.
