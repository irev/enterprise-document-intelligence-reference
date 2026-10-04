# RI-3.16 — Versioned Extraction Schema Boundary

Field extraction is constrained by an explicit, versioned ExtractionSchema.

A model/provider MUST NOT create arbitrary canonical field names or change the declared canonical value type. Extracted field names must exist in the selected schema and their value_type must match the registered FieldDefinition.

The extractor schema version must match the selected schema version. This keeps model output subordinate to platform-owned contracts and prevents a high-confidence extraction from silently expanding the canonical result shape.

The schema defines the allowed canonical field surface. Whether a field is required, conditionally required, or optional belongs to validation/profile policy rather than the extractor.
