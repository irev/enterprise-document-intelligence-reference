# Vision integration worklist

This is an implementation worklist, not a normative contract. Work proceeds in
dependency order; an unchecked item is not implemented merely because an issue
or adapter exists. Starting baseline: `c69e8f5`; this change adds the #40 converter
and derived-image provenance.

## 1. Derived-image provenance (implemented; prerequisite for 2–4)

- [x] Record renderer algorithm/library versions and all rendering limits.
- [x] Bind each image to tenant, application, document, processing run, source
  observation/digest, original page, image digest and dimensions.
- [x] Persist images and lineage atomically, immutably, with scoped reads.
- [x] Verify retry identity, changed-source/config rejection, reprocessing,
  restart durability, tenant isolation and original source-page mapping.

Implemented in `application/image_derivation.py` and
`adapters/sqlite_image_derivation.py`; tested in `tests/unit/test_image_derivation.py`.
This is an internal component, not yet wired into the API worker. The next task
is item 2; do not skip it to enable remote vision in the API serializer.

## 2. Multipage contract and orchestration (depends on 1)

- [x] Inspect specification and current result/evidence boundaries.
- [ ] Define a versioned aggregation policy: conflicting document types, missing
  or contradictory field values, UNKNOWN pages and partial page failures.
- [ ] Define how per-image evidence is represented in document-level results;
  retain original machine predictions and their derived-artifact lineage.
- [ ] Implement/test the agreed policy without inventing evidence or silently
  promoting partial analysis to complete document analysis.

Audit findings: `ProcessingResult.__post_init__` requires every evidence reference
to use the result's one observation ID/digest. `DocumentAnalyzer` returns page 1
relative to its supplied image. Combining those results by substituting the PDF
digest would falsify provenance. The specification's integrity schema permits
`DERIVED_ARTIFACT`; its source-observation schema is acquisition-specific and
must not be silently extended with rendering fields. Keep derivation as an
internal record until a compatible public projection is specified.

## 3. Worker/API integration (depends on 1 and 2)

- [ ] Snapshot provider, taxonomy, field matrix and rendering configuration.
- [ ] Preserve invocation-time tenant/application authorization and egress policy.
- [ ] Add an explicit, versioned result projection for region evidence and actual
  provider execution class; validate the relevant schema/examples.
- [ ] Wire converter, persisted derivations and analyzer into the worker with
  existing lease/retry/fail-safe and immutable-result semantics.

Audit findings: `ApiService.to_result` currently expects text `block_id`/`quote`
evidence and emits `LOCAL_MODEL`/`NONE` for model provenance. The vision adapter
uses region evidence and `REMOTE_MODEL`/`APPROVED_EXTERNAL`. Do not route its
results through that serializer unchanged. No external transmission is authorized
by rendering or lineage persistence alone.

## 4. End-to-end verification (depends on 3)

- [ ] Synthetic PDF -> real rendering -> mocked vision -> durable public result.
- [ ] Restart/retry, revoked authorization, partial failures, source mutation,
  cross-tenant access and schema validation.
- [ ] Confirm existing OCR processing remains available during migration.

## Deferred until the replacement flow is verified

- #44 runtime removal requires 1–4; do not remove existing runtime code early.
- #43 tenant field matrices and #41 advisory output require their own versioned
  contracts. They do not block image derivation persistence.

References checked locally: specification `SPECIFICATION.md`,
`docs/specification/NORMATIVE-MAP.md`, `schemas/source/source-observation.schema.json`,
`schemas/integrity/digest.schema.json`, `schemas/canonical/document-result-v2.schema.json`.
