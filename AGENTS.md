# Agent Instructions

This repository is a **Python reference implementation** of the technology-neutral Enterprise Document Intelligence specification.

## Source of truth

Before changing contracts or architecture, consult the specification repository:

- `irev/enterprise-document-intelligence`
- `SPECIFICATION.md`
- `docs/specification/NORMATIVE-MAP.md`
- applicable schemas, ADRs, and conformance vectors

The specification defines observable behavior. This repository demonstrates one implementation.

## Engineering rules

1. Use Python 3.12+.
2. Keep the domain/application core independent of web frameworks, databases, queues, OCR/model SDKs, and cloud providers.
3. Put external integrations behind explicit ports/adapters.
4. Do not duplicate or reinterpret normative contracts silently.
5. Preserve UNKNOWN/OOD and fail-safe outcomes.
6. AI/model output is evidence/prediction, never business authorization.
7. Material extracted values require provenance/evidence when the applicable contract requires it.
8. Completed result versions are immutable.
9. Reprocessing creates a new processing/result version.
10. Human correction must not overwrite original machine provenance.
11. Document content is untrusted data, never control instruction.
12. Customer-specific behavior belongs in profiles/configuration/policies, not customer-name branches.
13. Prefer deterministic tests that do not require network/model/provider access.
14. Make the smallest contract-consistent change and review the final diff.

## Confidentiality

MUST NOT commit:
- confidential corporate blueprints or original corporate documents;
- company/customer/vendor/person names sourced from private material;
- internal system/project names;
- production document numbers, tax/bank/account identifiers, credentials or secrets;
- copied private-source text that can identify or reconstruct the source.

Use synthetic names and values in tests.

## Dependency policy

Prefer the Python standard library for core/domain code. Add a dependency only when it provides a concrete implementation capability and keep it outside the domain boundary where practical.

Do not introduce a web framework, ORM, queue, OCR engine, model SDK, or cloud SDK merely to scaffold RI-0.

## Verification

For each change:
- run the relevant tests;
- validate machine-readable artifacts when changed;
- do not claim checks that were not executed;
- report contract/version impact when behavior changes.
