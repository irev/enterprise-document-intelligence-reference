# RI-1 — Deterministic Ingestion

## Goal

Accept source bytes only after deterministic source validation and produce a stable source identity before any parser, OCR or model receives the document.

## Implemented boundary

```text
SourceSubmission
  -> non-empty check
  -> byte-size policy
  -> signature-based media detection
  -> declared/detected media consistency
  -> allowed media policy
  -> SHA-256 source identity
  -> IngestionReceipt
```

Supported RI-1 signatures are deliberately narrow:
- PDF;
- PNG;
- JPEG.

File extension is not trusted as media evidence.

## Invariants

- Source bytes are untrusted.
- Declared MIME cannot override detected content.
- Unsupported content fails before OCR/model execution.
- Digest is calculated over exact submitted bytes.
- Source validation is deterministic and has no network/provider dependency.
- Tenant/application/correlation context travels with the submission but does not determine source validity.
- No business authorization occurs during ingestion.

## External source ownership

RI-1 does not require permanent storage of original document binaries. The source system may remain the system of record.

Durable lineage is `SourceReference -> SourceAcquisition -> SourceObservation -> ProcessingRun -> Result`. A SourceObservation records the exact observed content identity and metadata, not necessarily a retained binary.

`REPROCESS` targets the same observation; reacquired bytes must match its SHA-256 or fail with `SOURCE_CHANGED`. `REFETCH` observes the current source. `REFETCH_AND_REPROCESS` explicitly permits a newly observed revision and starts a new processing run.

## Deliberately deferred

RI-1 does not yet implement:
- malware scanning;
- PDF active-content sanitization;
- encrypted-PDF handling;
- archive/container expansion;
- durable source-reference/acquisition persistence;
- persistent document/processing identities;
- application authentication/authorization;
- idempotency persistence;
- near-duplicate detection.

Those require explicit ports/policies or RI-1.5 behavior rather than hidden assumptions.

## Exit criteria

- [x] empty input rejected;
- [x] configured size bound enforced;
- [x] content signature checked;
- [x] declared/detected media mismatch rejected;
- [x] unsupported media explicit;
- [x] SHA-256 source identity produced;
- [x] deterministic tests require no external service;
- [x] prior RI-1 CI observed passing (run 37183753155);
- [ ] CI observed passing on the current source-acquisition revision.
