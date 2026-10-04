# Enterprise Document Intelligence — Python Reference Implementation

Reference implementation for the technology-neutral [Enterprise Document Intelligence specification](https://github.com/irev/enterprise-document-intelligence).

## Status

**RI-0.5 — Shared service architecture foundation**

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

Use an activated project virtual environment for development commands.

The default suite installs development dependencies and runs the tests that do not require a live PostgreSQL DSN:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

PostgreSQL integration tests are conditional. If `EDI_TEST_POSTGRES_DSN` is not set, those tests are **skipped**; a default-suite success therefore does not by itself prove the durable PostgreSQL layer.

To run the PostgreSQL layer, install the adapter, point `EDI_TEST_POSTGRES_DSN` at a disposable test database, apply the migrations in order, then run the integration suite. For example, using the same database settings as CI:

```bash
python -m pip install -e ".[dev,postgres]"
export EDI_TEST_POSTGRES_DSN="postgresql://edi:edi@localhost:5432/edi_test"
export PGPASSWORD="edi"

psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0001_control_plane.sql
psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0002_inbound_outbox.sql
psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0003_source_lineage.sql
psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0004_processing_claim.sql
psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0005_observation_dispatch.sql
psql -h localhost -U edi -d edi_test -v ON_ERROR_STOP=1 -f migrations/0006_lineage_referential_integrity.sql

python -m pytest tests/integration -vv
```

On Windows PowerShell, set the environment variables with `$env:EDI_TEST_POSTGRES_DSN = "postgresql://edi:edi@localhost:5432/edi_test"` and `$env:PGPASSWORD = "edi"`; the migration and pytest commands are otherwise the same when `psql` is available on `PATH`.

See `AGENTS.md` before making architecture or contract changes.

The implementation is intended to operate as a shared service for multiple authorized consumer applications. See `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md`.
