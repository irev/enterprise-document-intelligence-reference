# RI-3.17 — Mandatory Extraction Schema Enforcement

The extraction application boundary now requires an explicit ExtractionSchema.

Raw extractor output is validated against the selected schema before duplicate-name, provenance and evidence checks complete. Arbitrary model-generated canonical field names, value-type changes and schema-version mismatches therefore fail before extraction output can be accepted.

There is no schema-less extraction path in the application contract. Provider/model output remains observational; the platform-owned extraction schema defines the canonical field surface.
