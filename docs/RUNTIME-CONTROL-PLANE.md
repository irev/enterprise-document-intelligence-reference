# Runtime Control Plane Contract

Status: reference-implementation contract. This document is not a normative business-domain specification.

CLI and Web Admin MUST call the same runtime-management application operations. The Web layer MUST NOT accept arbitrary shell commands, package-manager arguments, executable paths, or installer URLs from clients.

## Operations

| Operation | CLI | Web/API intent |
|---|---|---|
| Inspect host | `edi doctor` | `GET /admin/runtime/host` |
| List providers | `edi providers list` | `GET /admin/runtime/providers` |
| List models | `edi models list` | `GET /admin/runtime/models` |
| Plan provider install | `edi install --provider ... --profile ... --dry-run` | `POST /admin/runtime/providers/{id}/install-plans` |
| Execute provider install | reserved | reserved until privileged execution boundary is implemented |
| Verify provider | reserved | reserved |
| Pull/verify model | reserved | reserved |

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
