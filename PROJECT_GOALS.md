# Enterprise Document Intelligence — Project Goals

> **Scope:** Python reference implementation of the [technology-neutral specification](https://github.com/irev/enterprise-document-intelligence). The specification and versioned contracts prevail over implementation details.  
> **Governance:** This is a forward-looking tracking plan, **not** a declaration that its goals are implemented.  
> **Baseline date:** 2026-10-11. Re-audit repository status before delivery decisions.

## Product vision

Provide a secure, modular, multi-tenant, provider-agnostic **Document Intelligence shared service** that acquires, parses/OCRs, classifies, extracts, normalizes, validates, and returns evidence-linked document information to authorized applications. Request for Payment is one possible consumer, not the service's business workflow.

**Non-negotiable invariants**
- AI/model predictions are not business authorization.
- Untrusted document content must never become control instructions.
- Preserve UNKNOWN/OOD, uncertainty, safe-failure, evidence and lineage.
- Completed results are immutable; reprocessing appends a new version; human review preserves original machine provenance.
- Tenant/application boundaries are enforced server-side. No tenant-specific branches in core code.
- Keep domain and application layers free of provider SDK, web framework, database and cloud-specific dependencies.
- Never commit private corporate documents, personally identifying sample content or production credentials.

## Goal register

Priority: **P0** = must meet before production; **P1** = high value, staged delivery. Phase identifies suggested work sequence, **not** achieved status.

| ID | Goal | Priority | Phase | Dependencies | Tracking |
| --- | --- | --- | --- | --- | --- |
| G01 | Architecture & Contract Compliance | P0 | Foundation | — | [#22](https://github.com/irev/enterprise-document-intelligence-reference/issues/22) |
| G02 | Multi-Tenant & Shared Service | P0 | Integration | G01, G11 | [#23](https://github.com/irev/enterprise-document-intelligence-reference/issues/23) |
| G03 | Secure Document Ingestion | P0 | Integration | G02, G11 | [#24](https://github.com/irev/enterprise-document-intelligence-reference/issues/24) |
| G04 | Intelligent OCR & Parsing | P0 | Foundation | G01, G08 | [#25](https://github.com/irev/enterprise-document-intelligence-reference/issues/25) |
| G05 | Document Classification | P0 | Foundation | G04 | [#26](https://github.com/irev/enterprise-document-intelligence-reference/issues/26) |
| G06 | Structured Information Extraction | P0 | Intelligence | G05, G07 | [#27](https://github.com/irev/enterprise-document-intelligence-reference/issues/27) |
| G07 | Normalization & Validation | P0 | Foundation | G01 | [#28](https://github.com/irev/enterprise-document-intelligence-reference/issues/28) |
| G08 | Provider & Model Management | P1 | Intelligence | G01, G11 | [#29](https://github.com/irev/enterprise-document-intelligence-reference/issues/29) |
| G09 | Durable Processing & Workflow | P0 | Foundation | G01 | [#30](https://github.com/irev/enterprise-document-intelligence-reference/issues/30) |
| G10 | Standardized API & Integration | P0 | Integration | G02, G03, G06, G09 | [#31](https://github.com/irev/enterprise-document-intelligence-reference/issues/31) |
| G11 | Security, Privacy & Audit | P0 | Integration | G01 | [#32](https://github.com/irev/enterprise-document-intelligence-reference/issues/32) |
| G12 | Human-in-the-Loop Review | P1 | Intelligence | G06, G09, G11 | [#33](https://github.com/irev/enterprise-document-intelligence-reference/issues/33) |
| G13 | Admin Panel & Tenant Configuration | P1 | Intelligence | G02, G08, G11 | [#34](https://github.com/irev/enterprise-document-intelligence-reference/issues/34) |
| G14 | Cross-Platform Installation & Deployment | P1 | Production | G08, G09 | [#35](https://github.com/irev/enterprise-document-intelligence-reference/issues/35) |
| G15 | Quality, Observability & Production Readiness | P0 | Production | G01, G09, G11 | [#36](https://github.com/irev/enterprise-document-intelligence-reference/issues/36) |

## Delivery phases

1. **Foundation:** G01, G04, G05, G07, G09. Establish stable contracts, reproducible understanding, versioned results, durable recovery and PostgreSQL test evidence.
2. **Integration:** G02, G03, G10, G11. Enable authorized multi-application/multi-tenant ingestion, secure storage reference acquisition, results and audited API access.
3. **Intelligence:** G06, G08, G12, G13. Refine category-specific extraction quality, provider governance, operator tooling and human review.
4. **Production:** G14, G15. Demonstrate repeatable deployment, observable operations, load/quality/security gates and recovery procedures.

Phases can overlap when dependencies are met; **P0 security and verification are continuous**, not deferred to the end.

## Goal issue contract

Each linked goal issue is an **epic-style tracking issue**, not an isolated task. Its checklist defines observable acceptance criteria and evidence obligations. Implementation should be decomposed into bounded PRs or subtasks. Reuse and link relevant existing defects or PRs instead of making duplicate tasks.

For each issue:
1. Audit current `main` implementation against the normative specification.
2. Record **implemented / partial / missing / blocked**, with code and test links.
3. Execute minimal, contract-consistent changes; keep version impacts explicit.
4. Attach deterministic test evidence, CI results and PostgreSQL integration outcomes if persistence is touched. Report skipped/not-run tests explicitly.
5. Attach operational/security validation for affected trust boundaries.
6. Close only when every acceptance criterion is proven, not merely when code was merged.

## Release acceptance gates

A **pilot candidate** must demonstrate:
- At least two separate authorized consumer applications from distinct tenants, without cross-tenant data exposure.
- Safe authorized document acquisition, classification, schema-bound extraction and canonical JSON result validation.
- Traceable source/evidence/provenance and immutable result versioning.
- Fault/retry/restart and stale-worker safety, tested against the target durable store.
- Observability and operator runbooks for failures, review and recovery.

**Production readiness additionally requires measured targets and pass/fail evidence** for accuracy (by document/field class), latency, throughput, availability, security, backup/restore and RPO/RTO. Set numeric thresholds from representative, sanitized datasets and real deployment requirements—do not invent SLOs in advance.

## Current implementation / change boundaries (snapshot)

- `main` README describes **RI-5.13** as the current series and notes durable processing/evidence work still underway.
- Open PRs [#19](https://github.com/irev/enterprise-document-intelligence-reference/pull/19) (API v1), [#20](https://github.com/irev/enterprise-document-intelligence-reference/pull/20) (category schemas/normalizers), and [#21](https://github.com/irev/enterprise-document-intelligence-reference/pull/21) (storage references/JIT grants) describe **proposed unmerged work** as of this snapshot; do not present them as released `main` capabilities.
- Existing issue [#12](https://github.com/irev/enterprise-document-intelligence-reference/issues/12) is a crosscheck/roadmap discussion; existing issues [#1–#11](https://github.com/irev/enterprise-document-intelligence-reference/issues) are specific findings and should be cross-linked to goals during implementation, not duplicated.
- PostgreSQL integration tests require `EDI_TEST_POSTGRES_DSN`; skipped tests are not passing evidence.
- Model cache `WARMED / UPSTREAM_CACHE` is not equivalent to pinned, offline-verified model readiness.
- Source transport is a trust-boundary decision: prefer registered tenant storage references and tightly scoped short-lived grants; never trust arbitrary caller-supplied URLs.

## Ownership and maintenance

- **Owner:** repository maintainers (assign named owners per goal during triage).
- **Status source of truth:** linked GitHub issues, PRs, CI artifacts and normative specification, not this static snapshot.
- **Review cadence:** revisit priorities and blocked dependencies at each milestone; refresh this document when architectural goals change.
- **Change control:** contract changes require review of specification version, schema examples, conformance vectors and migration implications.

## Related references

- [Implementation README](https://github.com/irev/enterprise-document-intelligence-reference/blob/main/README.md)
- [Shared service architecture](https://github.com/irev/enterprise-document-intelligence-reference/blob/main/docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md)
- [Installation and operating instructions](https://github.com/irev/enterprise-document-intelligence-reference/blob/main/INSTALLATION.md)
- [AI coding agent rules](https://github.com/irev/enterprise-document-intelligence-reference/blob/main/AGENTS.md)
- [Normative specification](https://github.com/irev/enterprise-document-intelligence)
