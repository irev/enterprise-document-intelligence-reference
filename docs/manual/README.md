# Usage Manual

Operator and integrator usage manual for the Enterprise Document Intelligence Python
reference implementation. English; repository documentation conventions and the
confidentiality rules in `AGENTS.md` apply.

## Pages

| Page | Audience | Status |
|---|---|---|
| [Installation quickstart](installation.md) | Operator | current |
| [CLI reference](cli-reference.md) | Operator | current |
| [Day-to-day operations](operations.md) | Operator / integrator | partial — single-file `edi process` + `edi api` current; full submit/review pipeline not yet available |
| [Web control panel](web-panel.md) | Operator / admin | local read-only panel current (`edi web`); service/auth phases planned |
| [Troubleshooting index](troubleshooting.md) | Operator | current |

## Reading order

1. New host: [Installation quickstart](installation.md) → full runbook
   [`INSTALLATION.md`](../../INSTALLATION.md).
2. Commands: [CLI reference](cli-reference.md).
3. Failure handling: [Troubleshooting index](troubleshooting.md).
4. Service usage: [Day-to-day operations](operations.md) — read the status notes; several
   flows are not executable yet.
5. Background and roadmap: [`../REQUIREMENTS-ANALYSIS.md`](../REQUIREMENTS-ANALYSIS.md).

## Ground rules

- Every command shown here exists in the code base; anything not yet implemented is
  labeled **planned** and is never presented as runnable.
- ML provider dependencies must never be installed into the core `.venv`.
- NVIDIA profiles fail closed; there is no silent CPU fallback.
- Model states `WARMED` / `UPSTREAM_CACHE` are not offline-pinned artifact claims.
