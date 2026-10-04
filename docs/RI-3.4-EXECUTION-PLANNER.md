# RI-3.4 — Provider Registry and Execution Planner

The reference now models capability requirements independently from provider products.

A `ProviderCapability` advertises execution class, supported capabilities, version and egress behavior. An `ExecutionPolicy` constrains which execution classes and external data transfer are permitted.

The planner fails closed when no eligible provider satisfies both the capability request and policy. In particular, a local-only profile never silently widens to a remote provider.

Provider selection is deterministic in this reference. Registry order is deliberately not treated as preference policy; explicit preference/fallback chains will be a separate versioned policy contract.

The plan records provider/version and execution class before invocation. Concrete OCR/model adapters remain intentionally absent at this stage.
