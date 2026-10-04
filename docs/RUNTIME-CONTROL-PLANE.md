# Runtime Control Plane Contract

Status: reference-implementation contract. This document is not a normative business-domain specification.

CLI and Web Admin MUST call the same runtime-management application operations. The Web layer MUST NOT accept arbitrary shell commands, package-manager arguments, executable paths, or installer URLs from clients.

## Operations

| Operation | CLI | Web/API intent |
|---|---|---|
| Inspect host | `edi doctor` | `GET /admin/runtime/host` |
| List providers | `edi providers list` | `GET /admin/runtime/providers` |
| List models | `edi models list` | `GET /admin/runtime/models` |
| Status summary (host, VRAM tier, provider/model/server readiness) | `edi ps` | API `status.summary`; local panel route planned |
| Effective local configuration | `edi config` (`--wizard` writes `.edi/config.json`) | local console only (no HTTP surface) |
| Processing log read | `edi log` (`--tail`, `--follow`, `--pretty`) | local console only (no HTTP surface) |
| Tier map advisory | `edi serve recommend` | API `serve.recommend` (advisory only; never selects execution paths); local panel route planned |
| Plan provider install | `edi install --provider ... --profile ... --dry-run` | `POST /admin/runtime/providers/{id}/install-plans` |
| Execute provider install | `edi install ... --yes` | Local `edi web` panel: `POST /admin/runtime/providers/{id}/install` with `{"profile": "...", "confirm": true}` (confirm-gated, loopback, unauthenticated). Deployed Web Admin: **reserved** until privileged execution boundary is implemented |
| Verify provider | `edi ...` (planned) | reserved |
| Pull model | `edi models pull ... --yes` | Local `edi web` panel: `POST /admin/runtime/models/{id}/pull` with `{"profile": "...", "confirm": true}`. Deployed Web Admin: **reserved** |
| Verify model | `edi models verify` | reserved |
| List local inference servers | `edi serve list` | API `serve.list`; local panel route planned |
| Plan local server install | `edi serve plan --server ... [--via auto\|native\|docker]` | API `serve.plan` (read-only, code-owned vector) |
| Execute local server install | `edi serve install ... --yes` | API `serve.execute` with `{"confirm": true}` (confirm-gated). Deployed Web Admin: **reserved** |

The local `edi web` panel executes only with an explicit `confirm` flag (equivalent of `--yes`) and identifiers only; it is intended for loopback/trusted networks without authentication. The deployed Web Admin keeps the reserved status until authenticated admin identity and audit exist.

Local server install vectors are code-owned typed argument vectors: native package-manager
argv or a whitelisted Docker image reference (`ollama/ollama`, `vllm/vllm-openai`,
`linuxserver/lm-studio` — the LM Studio image is a community image and is labelled as
such). The API never accepts an image name, shell string, or installer URL from the
client. Tier recommendations (`runtime/tiers.toml`) are advisory output only; provider
selection keeps flowing `ProcessingProfile → ExecutionPolicy → ExecutionPlan`.

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
