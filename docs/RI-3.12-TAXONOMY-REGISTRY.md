# RI-3.12 — Versioned Taxonomy Boundary

Classifier output is constrained by an explicit, versioned document taxonomy.

A model/provider MUST NOT create new document types at runtime. Candidate types must be registered in the selected taxonomy or use the reserved UNKNOWN abstention value.

UNKNOWN is platform behavior rather than a configurable business document type and therefore cannot be registered as an ordinary taxonomy member.

The classifier taxonomy version must match the selected taxonomy version. This prevents predictions produced against one label space from being silently interpreted against another.

Tenant-specific aliases or business context must be mapped through configuration outside the canonical classifier label space rather than by allowing arbitrary model-generated labels.
