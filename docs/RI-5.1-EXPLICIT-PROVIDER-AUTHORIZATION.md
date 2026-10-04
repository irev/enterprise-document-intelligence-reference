# RI-5.1 — Explicit Provider Authorization Semantics

Provider authorization no longer overloads an empty collection with two meanings.

The reference contract now distinguishes:
- null/None allowlist: UNRESTRICTED at that authorization dimension;
- non-empty allowlist: only listed identities are authorized;
- explicit empty allowlist: DENY ALL.

PostgreSQL persists this distinction with tenant_access_mode and application_access_mode values UNRESTRICTED or ALLOWLIST. An ALLOWLIST mode with zero authorization rows therefore denies every identity.

This is security-significant. Removing the final authorization row from a restricted provider must revoke access rather than accidentally convert the provider to unrestricted access.

The application resolver now checks explicit nullability rather than collection truthiness, preserving fail-closed semantics.
