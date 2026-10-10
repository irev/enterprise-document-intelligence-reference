# Runtime Control Plane Contract

Status: reference-implementation contract. This document is not a normative business-domain specification.

CLI and Web Admin MUST call the same runtime-management application operations. The Web layer MUST NOT accept arbitrary shell commands, package-manager arguments, executable paths, or installer URLs from clients.

## Operations

| Operation | CLI | Web/API intent |
|---|---|---|
| Inspect host | `tlkdoc doctor` | `GET /admin/runtime/host` |
| List providers | `tlkdoc providers list` | `GET /admin/runtime/providers` |
| List models | `tlkdoc models list` | `GET /admin/runtime/models` |
| Status summary (host, VRAM tier, provider/model/server readiness) | `tlkdoc ps` | API `status.summary`; local panel `GET /admin/runtime/status` |
| Effective local configuration | `tlkdoc config` (`--wizard` writes `.edi/config.json`) | local console only (no HTTP surface) |
| Processing log read | `tlkdoc log` (`--tail`, `--follow`, `--pretty`) | local console only (no HTTP surface) |
| Tier map advisory | `tlkdoc serve recommend` | API `serve.recommend` (advisory only; never selects execution paths); local panel `GET /admin/runtime/servers/recommendations` |
| Plan provider install | `tlkdoc install --provider ... --profile ... --dry-run` | `POST /admin/runtime/providers/{id}/install-plans` |
| Execute provider install | `tlkdoc install ... --yes` | Local `tlkdoc web` panel: `POST /admin/runtime/providers/{id}/install` with `{"profile": "...", "confirm": true}` (confirm-gated, loopback, unauthenticated). Deployed Web Admin: **reserved** until privileged execution boundary is implemented |
| Verify provider | `tlkdoc ...` (planned) | reserved |
| Pull model | `tlkdoc models pull ... --yes` | Local `tlkdoc web` panel: `POST /admin/runtime/models/{id}/pull` with `{"profile": "...", "confirm": true}`. Deployed Web Admin: **reserved** |
| Verify model | `tlkdoc models verify` | reserved |
| List local inference servers | `tlkdoc serve list` | API `serve.list` (optional `runtime_root` for detection beyond PATH); local panel `GET /admin/runtime/servers` |
| Plan local server install | `tlkdoc serve plan --server ... [--via auto\|native\|docker] [--gpu auto\|on\|off] [--variant desktop\|headless]` | API `serve.plan` (read-only, code-owned vector, returns `start_hint`); local panel `POST /admin/runtime/servers/{id}/install-plans` |
| Execute local server install | `tlkdoc serve install ... --yes` | API `serve.execute` with `{"confirm": true}` (confirm-gated); local panel `POST /admin/runtime/servers/{id}/install` with `{"confirm": true}`. Deployed Web Admin: **reserved** |

The local `tlkdoc web` panel executes only with an explicit `confirm` flag (equivalent of `--yes`) and identifiers only; it is intended for loopback/trusted networks without authentication. The deployed Web Admin keeps the reserved status until authenticated admin identity and audit exist.

Local server install vectors are code-owned typed argument vectors: native package-manager
argv, a trusted stdlib bootstrap argv (Ollama on Linux downloads the vendor user-space
tarball into `.edi/runtimes/` — no sudo, no shell), or a whitelisted Docker image
reference (`ollama/ollama`, `vllm/vllm-openai`, `linuxserver/lm-studio` — the LM Studio
desktop image is a community image and is labelled as such; `lmstudio/llmster-preview`
is the official headless API image, selectable with `variant: "headless"`). The API
never accepts an image name, shell string, or installer URL from the client; `gpu`
(`auto`/`on`/`off`) and `variant` are validated enums, not free text. Tier
recommendations (`runtime/tiers.toml`) are advisory output only; provider selection
keeps flowing `ProcessingProfile → ExecutionPolicy → ExecutionPlan`.

## Security boundary

Installation recipes are trusted code-owned typed argument vectors. The provider manifest declares identity, capabilities, profiles, and model catalog only. It MUST NOT contain executable shell strings.

A future Web Admin submits identifiers such as:

```json
{
  "profile": "nvidia"
}
```

The server resolves that request to a trusted install plan. It never executes a browser-supplied command.

## PaddleOCR baseline

The current reference catalog exposes PP-OCRv6 medium as the default candidate, PP-OCRv5 server as a compatibility/benchmark candidate, and PP-StructureV3 for document layout. Production ProcessingProfile versions must pin the selected model; an upstream default change must not silently alter a historical or active profile.
