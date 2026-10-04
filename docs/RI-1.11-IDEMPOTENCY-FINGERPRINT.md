# RI-1.11 — Idempotency Request Fingerprint

Idempotency is scoped by tenant, application and idempotency key. A key is now bound to a deterministic fingerprint of the source request.

Replaying the same key with the same source request returns the existing inbound record and does not reacquire or redispatch.

Reusing the same key with materially different source identity fails with `IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST` before acquisition.

The fingerprint covers acquisition method, resource locator, connector identity, external version and expected digest. It deliberately excludes correlation/request identifiers because those identify transport interactions rather than source semantics.

Production persistence must enforce uniqueness for `(tenant_id, application_id, idempotency_key)` atomically. The application-level check is not a substitute for a database uniqueness constraint and transactional conflict handling.
