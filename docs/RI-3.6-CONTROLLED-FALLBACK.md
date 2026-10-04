# RI-3.6 — Controlled Runtime Fallback

Runtime fallback is represented as a new decision after an explicit failed execution attempt. It is not hidden inside a provider adapter.

An `ExecutionAttempt` records capability, provider identity/version, execution class, outcome and a stable failure code. Successful attempts cannot carry failure codes; failed attempts must carry one.

Fallback requires all of the following:
- the prior attempt explicitly failed;
- the capability was part of the original request;
- the execution policy enables fallback;
- the alternate provider remains inside allowed execution classes;
- data-egress restrictions still permit the alternate provider;
- the failed provider is excluded from fallback selection.

Therefore a local-only policy cannot silently cross into remote execution after a local provider failure.

Retrying the same provider, retry budgets/backoff, attempt persistence, latency/resource accounting and provider invocation are intentionally separate concerns and remain future work.
