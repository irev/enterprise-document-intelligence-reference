# Provider-Neutral Execution Boundary

Before adding a real OCR or AI implementation, the reference implementation treats provider choice as a control-plane concern.

## Required separation

```text
Application/Profile
       |
       v
Capability Request + Execution Constraints
       |
       v
Planner / Policy
       |
       v
Registered Provider Capability
       |
       v
Execution
       |
       v
Canonical Provider-Neutral Result
```

The application asks for an outcome, not a vendor.

Examples:
- application A: deterministic parser + OCR allowed; no model required;
- application B: local model only; remote data egress forbidden;
- application C: local preferred, approved remote fallback allowed;
- application D: classification disabled; extraction supplied externally.

A provider adapter cannot change tenant policy or widen its own permission.

## What must be stable first

1. source identity and immutable observation binding;
2. tenant/application authorization;
3. capability vocabulary;
4. provider registry contract;
5. versioned execution policy;
6. data-egress classification;
7. canonical result/evidence/provenance contracts;
8. deterministic failure taxonomy;
9. resource/time limits;
10. audit of plan, invocation and fallback.

Only after these boundaries are stable should concrete OCR/model adapters be added.

## Local-only operation

Local-only is a first-class deployment/profile, not a degraded mode. If a profile permits `LOCAL_MODEL` and forbids `REMOTE_MODEL`, failure of the local provider results in explicit failure/review according to policy. It never causes an implicit cloud fallback.
