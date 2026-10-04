# Enterprise Document Intelligence — Python Reference Implementation

Reference implementation for the technology-neutral [Enterprise Document Intelligence specification](https://github.com/irev/enterprise-document-intelligence).

## Status

**RI-5.13 — Provider authorization security complete; durable processing hardening continues**

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
     Provider ports      Conformance reporting
          |
          v
   Replaceable adapters
```

Initial package boundaries:

- `domain` — implementation-neutral domain values and outcomes.
- `contracts` — references to specification versions and observable contract vocabulary.
- `application` — use-case orchestration; no provider SDK dependencies.
- `adapters` — replaceable parser/OCR/classifier/extractor/storage/provider integrations.
- `conformance` — machine-readable reporting primitives for specification conformance.

## RI-0 acceptance criteria

RI-0 is complete when the implementation can:

1. identify the specification and contract versions it targets;
2. declare supported capabilities;
3. represent explicit processing/result states without inventing business authorization;
4. represent conformance outcomes through provider-neutral machine-readable reporting;
5. emit a machine-readable conformance report shape;
6. run deterministic unit tests without OCR/model/network dependencies.

## Milestone progression

RI-0 through RI-4 established the portable contract, deterministic ingestion, parser/OCR, classification/extraction, and normalization/validation foundations.

RI-5 is the active durability and control-plane series. RI-5.0 through RI-5.13 cover PostgreSQL control-plane persistence, explicit provider authorization, durable inbound/outbox and source lineage, processing ownership/lease fencing, observation identity and referential integrity, long-running processing safety, and tenant-scoped provider authorization.

The next implementation work continues durable processing/result/evidence behavior before human review and shared-service production hardening.

## Confidentiality

This repository MUST NOT contain confidential corporate blueprints, source documents, organization/customer/vendor/person identities, internal system names, production identifiers, credentials, bank/tax identifiers, or source-derived material that can identify a private source.

Private material may inform validation privately. Only generalized, sanitized, non-identifying implementation requirements or test cases may be committed.

## Installation\n\nUse [`INSTALLATION.md`](INSTALLATION.md) for operator installation, isolated PaddleOCR runtime provisioning, model warm/verification, GPU profile selection, and troubleshooting. Do not install ML provider dependencies into the core development environment.\n\n## Development\n
Use an activated project virtual environment for development commands.

The default suite installs development dependencies and runs the tests that do not require a live PostgreSQL DSN:

```bash
python -m pip install -e ".[dev]"
python -m pytest
```

PostgreSQL integration tests are conditional. If `EDI_TEST_POSTGRES_DSN` is not set, those tests are **skipped**; a default-suite success therefore does not by itself prove the durable PostgreSQL layer.

To run the PostgreSQL layer, install the adapter, point `EDI_TEST_POSTGRES_DSN` at a disposable test database, apply migrations through the versioned runner, then run the integration suite:

```bash
python -m pip install -e ".[dev,postgres]"
export EDI_TEST_POSTGRES_DSN="postgresql://edi:edi@localhost:5432/edi_test"

python scripts/apply_migrations.py --dsn "$EDI_TEST_POSTGRES_DSN"
python -m pytest tests/integration -vv
```

The migration runner discovers ordered `NNNN_*.sql` files automatically and records their filename and SHA-256 in `control_plane.schema_migration`. Applied versions are skipped on rerun; changing an already-applied migration fails checksum verification instead of silently accepting schema drift.

On Windows PowerShell, set `$env:EDI_TEST_POSTGRES_DSN = "postgresql://edi:edi@localhost:5432/edi_test"`, then run:

```powershell
python scripts/apply_migrations.py --dsn $env:EDI_TEST_POSTGRES_DSN
python -m pytest tests/integration -vv
```

See `AGENTS.md` before making architecture or contract changes.

The implementation is intended to operate as a shared service for multiple authorized consumer applications. See `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md`.
