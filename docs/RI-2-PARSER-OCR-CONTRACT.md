# RI-2 — Parser/OCR Adapter Contract

## Objective

Define a secure, provider-neutral document-understanding boundary before choosing a concrete PDF parser or OCR engine.

## Boundary

```text
SourceObservation + ephemeral bytes
  -> isolated ParserAdapter
  -> page-ordered content
  -> optional OCR adapter
  -> provenance-bound UnderstandingResult
```

The result is bound to the exact observation SHA-256 and records parser/OCR component versions.

## Security requirements for real adapters

Document bytes and embedded objects are untrusted input. A production parser/OCR adapter MUST enforce or run inside controls providing:
- execution isolation appropriate to parser risk;
- bounded CPU, memory, temporary storage and wall-clock time;
- maximum page count and extracted-output limits;
- protection against recursive/container expansion and decompression bombs;
- explicit encrypted/corrupt/unsupported outcomes;
- no execution of embedded scripts, macros, actions or attachments;
- no outbound network access unless an explicitly authorized provider adapter requires it;
- cleanup of temporary files on success, failure and timeout;
- dependency/version inventory suitable for vulnerability response.

A provider adapter using remote OCR MUST treat document transfer as a separate authorized data egress. Tenant/profile policy must permit the provider and data region/retention behavior where applicable.

## Failure semantics

Stable codes include:
- `ENCRYPTED_DOCUMENT_UNSUPPORTED`
- `CORRUPT_DOCUMENT`
- `PAGE_LIMIT_EXCEEDED`
- `RESOURCE_LIMIT_EXCEEDED`
- `PARSER_TIMEOUT`
- `OCR_TIMEOUT`
- `PARSER_FAILED`
- `OCR_FAILED`

Provider exception text, local paths, commands and secrets are not public failure messages.

## Provenance

Page numbering is one-based and contiguous in the canonical adapter output. Each page records parser component/version and, when OCR is used, OCR component/version.

Parser/OCR output remains untrusted content. Extracted document text MUST NOT be interpreted as system instructions or allowed to modify control policy.
