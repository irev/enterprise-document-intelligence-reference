# Web Control Panel

**Status: local panel shipped** (`tlkdoc web`) with read-only views plus **confirm-gated
install/model-download execution**; authenticated service deployment and verify
operations remain planned. The panel is a stdlib `http.server` adapter in
`adapters/web_panel.py` — no HTTP framework, no new dependency, no CDN assets.

## Running the panel

```text
tlkdoc web --port 4099                    # bind 127.0.0.1 (default), port 4099 (default)
tlkdoc web --port 4099 --hostname 0.0.0.0 # expose on all interfaces — no authentication!
```

Prints the listening URL, then serves until Ctrl+C. Three pages behind the header
nav. Every rendered value comes from a live operation response — the panel contains
no mock or placeholder data:

**Overview** (read-only by construction):

| Route | Delegates to | CLI counterpart |
|---|---|---|
| `GET /` | built-in HTML page (local assets only) | — |
| `GET /admin/runtime/host` | `doctor` | `tlkdoc doctor` |
| `GET /admin/runtime/status` | `status.summary` (body param `runtime_root`) | `tlkdoc ps` |
| `GET /admin/runtime/providers` | `providers.list` | `tlkdoc providers list` |
| `GET /admin/runtime/models` | `models.list` | `tlkdoc models list` |

**Servers** (read + plan, plus confirm-gated execution):

| Route | Delegates to | Body |
|---|---|---|
| `GET /admin/runtime/servers` | `serve.list` | — |
| `GET /admin/runtime/servers/recommendations` | `serve.recommend` (advisory) | — |
| `POST /admin/runtime/servers/{id}/install-plans` | `serve.plan` (read-only) | `{"via": "auto\|native\|docker", "gpu": "auto\|on\|off", "variant": "desktop\|headless", "model": "..."}` |
| `POST /admin/runtime/servers/{id}/install` | `serve.execute` | `{"via": "...", "gpu": "...", "variant": "...", "model": "...", "confirm": true}` |

**Install** (confirm-gated execution, staged animation plan → install → download):

| Route | Delegates to | Body |
|---|---|---|
| `POST /admin/runtime/providers/{id}/install-plans` | `install.plan` (read-only plan preview) | `{"profile": "..."}` |
| `POST /admin/runtime/providers/{id}/install` | `install.execute` | `{"profile": "...", "confirm": true}` |
| `POST /admin/runtime/models/{id}/pull` | `models.pull` | `{"profile": "...", "confirm": true}` |

`confirm: true` is the equivalent of `--yes`; without it the response is
`400 CONFIRMATION_REQUIRED`. The page shows real step progress: a pulsing stage list
(plan / install / download) plus an animated progress bar while each request is in
flight — the CLI shows matching spinner animations on stderr during `tlkdoc install` and
`tlkdoc models pull` (TTY only; stdout JSON stays byte-identical).

Everything else fails closed: verify routes (`providers/{id}/verify`,
`models/{id}/verify`, `servers/{id}/verify`) answer `403 RESERVED_OPERATION`;
unknown paths `404 NOT_FOUND`; wrong methods `405`; malformed bodies
`400 INVALID_REQUEST` / `INVALID_PARAMS`. Every route calls the *same* operation
dispatcher as `tlkdoc api` — one implementation, identifiers only.

## Security posture

- Default bind is `127.0.0.1`. `--hostname 0.0.0.0` exposes an **unauthenticated**
  panel — including confirm-gated install/pull — to the network; trusted networks only.
- Execution requires explicit `confirm` (equivalent of `--yes`); clients send
  identifiers only, the server resolves trusted, code-owned commands
  (`docs/RUNTIME-CONTROL-PLANE.md`).
- Plan operations plan only: nothing is created or executed
  (`docs/RUNTIME-CONTROL-PLANE.md:14`).
- Static assets are fully local (air-gap: no CDN/fonts/scripts); responses carry
  `Cache-Control: no-store`.

## Contract that binds CLI and Web

- CLI and Web Admin MUST call the **same** runtime-management application operations; the
  web layer is an adapter, not a second implementation
  (`docs/RUNTIME-CONTROL-PLANE.md:5`).
- The web layer MUST NOT accept shell commands, package-manager arguments, executable
  paths, or installer URLs. Clients send identifiers only, e.g. `{"profile": "nvidia"}`;
  the server resolves a trusted, code-owned install plan
  (`docs/RUNTIME-CONTROL-PLANE.md:21-31`).

## Phases

### Phase 0 — CLI parity (prerequisite)

Shipped: `tlkdoc api` (JSON envelope), `tlkdoc process`, `tlkdoc ps` (fleet status +
`status.summary`), the GPU tier view, and `tlkdoc serve` (`serve.*` API operations).
Stable `--json` outputs for `providers list`/`models list` remain
(`../REQUIREMENTS-ANALYSIS.md` §4.2).

### Phase 1 — read-only runtime views — **shipped** (`tlkdoc web`)

The read routes in the table above are implemented exactly as specified in
`docs/RUNTIME-CONTROL-PLANE.md:11-14`.

### Phase 2 — execution operations — **partially shipped (local panel)**

- Shipped: confirm-gated `install.execute` and `models.pull` on the local `tlkdoc web`
  panel with the staged plan → install → download animation. Confirmation is the
  `confirm: true` field (equivalent of `--yes`), identifiers only, server-side typed
  argv.
- Shipped: `status.summary` on Overview (fleet readiness + VRAM tier) and the
  **Servers** page — `serve.list` / `serve.recommend` (advisory) read routes plus
  `serve.plan` and confirm-gated `serve.execute` with the staged plan → install
  animation. The Servers card offers the GPU intent (`auto` / `on` / `off`) and, for
  LM Studio over Docker, the image variant (`desktop` GUI / `headless` API) —
  identifiers only, forwarded verbatim to the API, which validates them.
  Console equivalents: `tlkdoc ps` and `tlkdoc serve ...`.
- Still reserved: verify routes, and all execution on a deployed Web Admin —
  `docs/RUNTIME-CONTROL-PLANE.md` records the boundary. Requirements when the deployed
  boundary is lifted: authenticated admin identity, audit entries in
  `configuration_audit`.

### Phase 3 — data-plane operations dashboard

Module IA from `docs/RI-0.5-SHARED-SERVICE-ARCHITECTURE.md:106-123`: Dashboard,
Inbound, Processing, Documents, Review, Outbound, Findings, Applications, Tenants,
Providers, Profiles/Policies, Audit — reading the control-plane and processing schema
(`migrations/0001`–`0016`). Authorization is independent of UI visibility; the panel
must never contain payment approval or other business authorization.

## Implementation constraints

- Domain/application core stays framework-free; any web dependency lives in the adapters
  layer and only for a concrete capability (`AGENTS.md`).
- The shipped Phase 1 panel is a stdlib `http.server` adapter — no new dependency. A
  framework extra is an option only from Phase 2 needs onward, together with the
  privileged execution boundary.
- Authentication is required before any non-local bind in a deployed setting; the local
  panel intentionally has none and must stay on trusted networks.
- Secrets are never exposed in views or logs; raw document access is separately
  authorized and auditable.
- Fail-closed and `UNKNOWN` outcomes are preserved in every view.
