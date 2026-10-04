# RI-3.10 — Extraction to Normalization Lifecycle

Extraction and normalization are distinct pipeline stages.

Extraction produces observed field state, raw value, confidence, evidence and extractor provenance. It MUST NOT manufacture or require a normalized value.

Normalization consumes a PRESENT extracted field and produces a versioned NormalizedValue with independent normalizer provenance. Missing, explicit-null and invalid fields are not normalized by this stage.

The combined NormalizedField retains the original ExtractedField, preserving raw value, evidence, confidence and extractor provenance alongside the normalized representation.

This separation prevents provider/model extraction output from being treated as deterministic canonical normalization and allows normalization rules to evolve/version independently from extractors.
