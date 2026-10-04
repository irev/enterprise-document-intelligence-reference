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

## Deliberately deferred

RI-1 does not yet implement:
- malware scanning;
- PDF active-content sanitization;
- encrypted-PDF handling;
- archive/container expansion;
- durable object storage;
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
- [ ] CI observed passing on current main revision.
