# RI-5.0 — PostgreSQL Control Plane Foundation

The first durable reference persistence slice is the provider authorization control plane.

Migration 0001 defines tenant/application identity, provider configuration, tenant/application provider authorization, versioned execution policy storage and configuration audit tables.

Application code now depends on a ProviderConfigurationSource port. The existing in-memory registry remains a test implementation; PostgreSqlProviderConfigurationSource is the first durable adapter.

The PostgreSQL adapter intentionally uses a DB-API compatible connection factory rather than importing a concrete driver into the application/domain layers. Driver and pooling selection remain deployment concerns.

This slice does not yet claim a live PostgreSQL integration test. The next persistence step must add a real database test environment and prove the ADR-0011 sequence across committed transactions: plan while authorized, revoke authorization, then reject invocation before provider code runs.

Important: provider authorization semantics must distinguish unrestricted configuration from an explicit empty authorization set. Until that distinction is represented durably, production authorization should not rely on empty allowlist meaning alone.
