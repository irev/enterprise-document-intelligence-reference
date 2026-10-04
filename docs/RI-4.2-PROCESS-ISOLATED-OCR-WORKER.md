# RI-4.2 — Process-Isolated OCR Worker

Local OCR execution can now be wrapped in ProcessIsolatedOcrEngine.

Each invocation executes the concrete LocalOcrEngine in a child process. The parent enforces the invocation deadline independently of the OCR library. On timeout the child is terminated and, after a bounded grace period, killed if necessary. Engine exceptions are converted to a sanitized OCR_WORKER_FAILED error.

This boundary provides:
- hard wall-clock timeout independent of engine API;
- crash containment for native/model code;
- no propagation of engine exception details across the boundary;
- guaranteed parent-side cleanup of IPC handles.

The worker does not select providers, change execution policy, perform network fallback, or make business decisions.

## Remaining production controls

This reference boundary does not yet impose OS-level CPU, memory, GPU or filesystem quotas. Production deployments should add platform-appropriate sandbox/resource controls around worker processes. Engine factories must also be spawn-safe on platforms using multiprocessing spawn.
