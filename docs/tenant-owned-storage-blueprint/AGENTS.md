# AI Coding Agent — Tenant-Owned Storage Document Intelligence

Read `BLUEPRINT.md` before changing storage integration, ingestion, authorization, batch processing, extraction, result delivery, networking or deployment. Treat MUST/MUST NOT as enforceable invariants. If repo implementation conflicts with blueprint, report conflict and propose ADR; do not silently bypass.

## Priority
Correctness > security > maintainability > simplicity > performance.

## Mandatory checks
1. Identify component/data owner and affected trust boundaries.
2. Obtain tenant identity from verified auth, never caller-provided `tenant_id`.
3. Accept only opaque document references mapped to registered storage origins, not arbitrary URLs.
4. Use per-object short-lived read grants just in time; never persist bearer URLs in normal jobs, queues, logs, traces or errors.
5. Validate egress destination and enforce deny-by-default network policy beyond application code.
6. Pin object version or verify integrity; quarantine and sandbox untrusted bytes.
7. Make jobs idempotent and retries bounded; handle partial batch failures.
8. Apply residency and external-model policy before and during processing; local-only must not fall back to cloud.
9. Preserve field evidence, output schema and model version; never invent missing extracted values.
10. Add cross-tenant, SSRF, leak, failure and cleanup tests; run relevant checks and inspect git diff.

Do not invent a provider-neutral guarantee of single-use Signed URLs. For actual one-time access, implement an atomic redemption gateway and test replay rejection.

Keep tenant-specific business behavior in validated versioned policies/profiles. Avoid changes to core security invariants. Request architectural approval for exceptions.
