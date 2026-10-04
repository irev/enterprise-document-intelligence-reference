# RI-5.11 — Canonical Source Observation

The reference implementation uses one canonical `SourceObservation` domain model for durable source lineage.

## Domain ownership

### Source reference

A source reference describes how or where source material may be acquired. Examples include upload, signed URL, or connector addressing. It is not proof that particular bytes were observed.

Credentials and secrets are not observation attributes and must not be embedded in durable observation identity.

### Source acquisition

An acquisition represents an attempt to obtain source material. Attempt-specific state belongs here, including acquisition method, status, time, failure information, and the observation produced by a successful acquisition.

Transport or connector interaction metadata such as ETag and connector version describes acquisition/source interaction. It must not be used as the identity of observed bytes.

### Source observation

`SourceObservation` is the canonical immutable factual record of bytes observed for a scoped document:

- observation identity;
- document identity;
- tenant and application scope;
- SHA-256 integrity digest;
- byte length;
- detected media type;
- observation time;
- external source version when supplied.

SHA-256 is an integrity attribute, not observation identity.

An accepted acquisition must provide factual byte length and detected media type. The implementation must not fabricate fallback values merely to construct an observation.

## Processing lineage

Processing, dispatch, claims, understanding, and future evidence/result records bind to `observation_id`. Digest values may be carried for integrity verification but do not replace observation identity.

The canonical relationship is:

```text
SourceReference
      |
      v
SourceAcquisition
      |
      v
SourceObservation
      |
      +--> ProcessingRun
      +--> Outbox dispatch
      +--> ProcessingClaim
      +--> Understanding
      +--> Evidence / Result (future)
```

## Compatibility

RI-5.11 removes the earlier duplicate observation representation. The former `ScopedObservation` name is not retained as a compatibility alias, so new code has one domain term and one authoritative observation shape.

Database table names remain unchanged; this milestone is a domain-model canonicalization rather than a storage rename.
