# Enterprise Document Intelligence — Python Reference Implementation

Reference implementation for the technology-neutral [Enterprise Document Intelligence specification](https://github.com/irev/enterprise-document-intelligence).

## Status

**RI-0 — Contract and conformance foundation**

This repository demonstrates one possible implementation of the specification. It is **not** the normative source of platform behavior. When implementation behavior conflicts with the specification, the specification and its versioned contracts take precedence.

## Runtime

- Python 3.12+
- Standard library first
- External dependencies are introduced only when a concrete capability requires them

No web framework, database, queue, OCR engine, model provider, or cloud platform is mandated by RI-0.

## Architecture

```text
Specification / schemas / conformance vectors
                    |
                    v
             Contract boundary
                    |
                    v
              Application core
                    |
          +---------+---------+
          |                   |
          v                   v
     Provider ports      Conformance adapter
          |
          v
   Replaceable adapters
```

Initial package boundaries:

- `domain` — implementation-neutral domain values and outcomes.
- `contracts` — references to specification versions and observable contract vocabulary.
- `application` — use-case orchestration; no provider SDK dependencies.
- `adapters` — replaceable parser/OCR/classifier/extractor/storage/provider integrations.
- `conformance` — adapter and runner support for specification conformance vectors.

## RI-0 acceptance criteria

RI-0 is complete when the implementation can:

1. identify the specification and contract versions it targets;
2. declare supported capabilities;
3. represent explicit processing/result states without inventing business authorization;
4. map abstract conformance input/output through a provider-neutral adapter;
5. emit a machine-readable conformance report shape;
6. run deterministic unit tests without OCR/model/network dependencies.

## Planned sequence

```text
RI-0 Contract + Conformance
  -> RI-1 Deterministic Ingestion
  -> RI-2 Parser / OCR Adapter
  -> RI-3 Classification + Extraction
  -> RI-4 Normalization + Validation
  -> RI-5 Versioning + Human Review
  -> RI-6 Bundle + Business Profile
```

## Confidentiality

This repository MUST NOT contain confidential corporate blueprints, source documents, organization/customer/vendor/person identities, internal system names, production identifiers, credentials, bank/tax identifiers, or source-derived material that can identify a private source.

Private material may inform validation privately. Only generalized, sanitized, non-identifying implementation requirements or test cases may be committed.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

See `AGENTS.md` before making architecture or contract changes.
