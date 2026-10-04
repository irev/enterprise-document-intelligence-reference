# RI-3.19 — Plan-to-Invocation Control-Plane Authorization

A provider selected during planning must be resolved again through current control-plane configuration before invocation.

The authorization boundary verifies planned provider identity, version, execution class and capability, then applies current enabled state and tenant/application allowlists.

This prevents a stale execution plan from bypassing a provider that was disabled or whose tenant/application authorization changed after planning.

Planning is selection, not authorization. Invocation-time authorization is fail-closed and uses current control-plane state.
