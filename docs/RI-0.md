# RI-0 — Contract and Conformance Foundation

## Goal

Establish a Python implementation boundary that consumes the normative specification without turning Python-specific design into platform requirements.

## In scope

- Python package boundary.
- Explicit specification target.
- Provider-neutral domain outcomes.
- Capability declaration vocabulary.
- Conformance adapter interface.
- Machine-readable conformance report primitives.
- Deterministic tests and CI.

## Out of scope

- HTTP API.
- Database/storage implementation.
- OCR/parser provider.
- classifier/extractor model.
- RFP/customer workflow.
- payment/accounting authorization.
- private corporate fixtures.

## Exit criteria

- [x] Repository identifies itself as a non-normative implementation.
- [x] Python 3.12+ package is bootstrapped.
- [x] Core has no runtime third-party dependency.
- [x] Specification version target is explicit.
- [x] Conformance adapter boundary exists.
- [x] Report output follows the normative report vocabulary.
- [x] Unit/conformance tests exist.
- [x] CI workflow exists.
- [x] RI-0 CI was observed passing during the RI-0 milestone. Current-main CI status is tracked by GitHub Actions, not by this historical checklist.

RI-1 MUST NOT start by introducing a framework. It starts from deterministic source ingestion semantics: source bytes, integrity, MIME/content validation, tenant boundary, and processing identity.
