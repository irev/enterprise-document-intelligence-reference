# RI-2.3 — Evidence Model Integration

## Objective

Make machine claims traceable to immutable source structure before classification and extraction are introduced.

## Evidence reference

An evidence reference binds to:
- SourceObservation ID;
- SourceObservation SHA-256;
- page;
- evidence kind;
- canonical block/table-cell/region locator;
- optional source quote.

Supported reference kinds in this slice are `TEXT_BLOCK`, `TABLE_CELL`, and `REGION`.

## Resolution

```text
Prediction
  -> EvidenceReference
       -> SourceObservation
       -> StructuredDocument
       -> Page
       -> Block / TableCell / Region
```

An observation or digest mismatch is invalid. Evidence cannot be silently rebound to another version of a source document.

For block/cell evidence, an optional quote is validation metadata: when present it must occur in the referenced canonical source text. It is not a replacement for the structural locator.

## Security and privacy

Evidence references are tenant-scoped through their parent result/document authorization. Knowing a block ID, digest or observation ID grants no access.

Quotes can contain sensitive document data. APIs and telemetry SHOULD avoid duplicating source text unless needed for authorized review. A UI can resolve an evidence locator against authorized document structure rather than receiving broad raw text by default.

Evidence provenance demonstrates where a machine claim came from. It does not prove that the underlying document is authentic or that the claim is business-valid.
