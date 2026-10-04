# RI-4.6 — Authorized Planned Invocation

The execution path now has a single application-level entry point that binds a PlannedStep to current control-plane authorization immediately before provider invocation.

invoke_planned_provider:
1. verifies the plan still matches the registered ProviderCapability;
2. resolves the provider against current enabled state and tenant/application allowlists;
3. constructs InvocationRequest from the planned capability, provider identity and execution class;
4. passes the request through the existing fail-closed invocation boundary.

A stale plan therefore cannot bypass a provider that was disabled or removed from a tenant/application after planning. Authorization failure occurs before provider code is called.

This closes the earlier gap where authorize_planned_provider existed as a helper but callers could invoke the lower-level provider boundary without using it. Lower-level invoke_provider remains an internal composition primitive; shared-service orchestration should use invoke_planned_provider when executing a plan.
