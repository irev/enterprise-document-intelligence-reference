# RI-3.13 — Classification Taxonomy Enforcement

The versioned taxonomy is now enforceable at the classification application boundary rather than existing only as a standalone validation utility.

When a taxonomy is supplied, every raw classifier candidate is validated before confidence and margin decisions are applied. An unregistered model label or taxonomy-version mismatch fails explicitly and cannot be converted into an accepted prediction.

The taxonomy argument remains optional temporarily for compatibility with earlier reference milestones. Production profiles that enable classification must select a taxonomy. A later contract-hardening milestone may make the taxonomy mandatory after dependent examples and adapters are migrated.
