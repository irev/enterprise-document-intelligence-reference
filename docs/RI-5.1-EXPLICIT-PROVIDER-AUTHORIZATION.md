# RI-5.1 — Explicit Provider Authorization Semantics

Provider authorization no longer overloads an empty collection with two meanings.

The reference contract now distinguishes:
- null/None allowlist: UNRESTRICTED at that authorization dimension;
- non-empty allowlist: only listed identities are authorized;
- explicit empty allowlist: DENY ALL.

PostgreSQL persists this distinction with tenant_access_mode and application_access_mode values UNRESTRICTED or ALLOWLIST. An ALLOWLIST mode with zero authorization rows therefore denies every identity.

This is security-significant. Removing the final authorization row from a restricted provider must revoke access rather than accidentally convert the provider to unrestricted access.

The application resolver now checks explicit nullability rather than collection truthiness, preserving fail-closed semantics.


## Tenant-scoped application identity

Application authorization is evaluated against the pair `(tenant_id, application_id)`, not against `application_id` globally.

This matters when application identifiers are tenant-local. Authorizing `tenant-a/shared-app` MUST NOT authorize `tenant-b/shared-app`, even when tenant access itself is unrestricted. The PostgreSQL adapter therefore preserves both columns when loading application authorization rows, and the resolver checks the exact pair.

Authorization is re-resolved from current trusted control-plane state immediately before provider invocation. A previously selected execution plan is not an authorization grant: revoking the tenant/application pair must block a later invocation that attempts to reuse that stale plan.

Integration coverage uses two tenants with the same application identifier to prevent future flattening of application authorization scope.
