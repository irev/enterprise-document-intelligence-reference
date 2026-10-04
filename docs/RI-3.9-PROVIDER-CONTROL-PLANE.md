# RI-3.9 — Provider Configuration and Control Plane

Provider capability declaration and deployment configuration are separate contracts.

A provider configuration contains only control-plane references and routing restrictions: enabled state, version, deployment zone, engine reference, optional secret reference, optional endpoint reference, and tenant/application allowlists.

`secret_ref` is an opaque reference. Secret material MUST NOT be placed in this object, execution plans, invocation requests, canonical results, audit events or document content.

`endpoint_ref` is also an opaque deployment reference rather than an arbitrary request URL. The deployment adapter resolves it from trusted configuration. This preserves the existing SSRF boundary.

Provider configuration can restrict a provider to selected tenants/applications. These restrictions narrow access; they do not grant a tenant permission to widen execution-class or data-egress policy.

A local-only deployment can therefore register only local provider configurations, while another deployment can register local and approved external providers without changing core contracts.

Health probing, secret resolution, endpoint resolution and persistence are adapter/infrastructure concerns. Concrete OCR/model product configuration remains intentionally outside the canonical domain.
