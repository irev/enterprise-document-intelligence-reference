# Troubleshooting Index

Quick index of failure codes and where the full procedure lives. Authoritative details:
[`INSTALLATION.md`](../../INSTALLATION.md) §10 (Troubleshooting) and §11 (Verification
checklist). CLI-specific codes: [CLI reference](cli-reference.md).

## Decision rule

- A failure is a **host/runtime problem** → correct the host; never force a profile,
  never hand-install provider packages into the core `.venv`, never bypass verification.
- A failure is a **dev-toolchain problem** (mypy/`librt`) → fix the environment; do not
  add `librt` or provider packages as a workaround.

## Error codes

| Code | Meaning | First action |
|---|---|---|
| `NVIDIA_RUNTIME_NOT_DETECTED` | Requested `nvidia` profile but no usable NVIDIA runtime found | `edi doctor`, `nvidia-smi`; use CPU profile or fix host — do not force the profile (`INSTALLATION.md:508-517`) |
| `NVIDIA_DRIVER_VERSION_REQUIRED` | `nvidia-smi` present but driver version unresolvable | Fix the NVIDIA installation before retrying (`INSTALLATION.md:519-521`) |
| `NVIDIA_DRIVER_TOO_OLD` | Driver below the trusted recipe floor | Upgrade driver or use CPU profile (`INSTALLATION.md:523-525`) |
| `INSTALL_STEP_FAILED:<step>` | Isolated runtime created; one install step failed | Inspect interactive output + redacted `install-state.json`, fix cause, rerun same provider/profile (`INSTALLATION.md:527-531`) |
| `PADDLE_RUNTIME_NOT_INSTALLED` | `models pull` before profile install | Install the profile first (`INSTALLATION.md:533-535`) |
| `PADDLE_RUNTIME_NOT_READY` | Runtime state is not `READY` (install failed or incomplete) | Re-run `edi install` for that profile; check `install-state.json` (`cli.py:163-164`) |
| `MODEL_WARM_FAILED` | Model warm failed | Check network, upstream availability, runtime health, disk; retry same model/source (`INSTALLATION.md:537-539`) |
| `MODEL_ARTIFACT_INTEGRITY_MISMATCH` | Local provenance manifest changed after recording | Treat state as invalid, reprovision; never bypass verification (`INSTALLATION.md:541-543`) |
| `RUNTIME_INCOMPATIBLE` | Requested profile incompatible with detected host | Command exits before execution; use a compatible profile or fix host (`cli.py:188-191`) |
| `INSTALL_CONFIRMATION_REQUIRED_USE_YES` | `edi install` without `--yes` | Re-run with `--yes` after reviewing `--dry-run` (`cli.py:211`) |
| `MODEL_PULL_CONFIRMATION_REQUIRED_USE_YES` | `models pull` without `--yes` | Re-run with `--yes` (`cli.py:154`) |

## Windows: mypy fails with `librt.base64`

Full procedure: `INSTALLATION.md:460-506` and `README.md` (Windows mypy section).
Summary: confirm `python -m mypy` runs inside `.venv\Scripts\python.exe` on Python 3.12;
recreate the venv if a machine-wide interpreter is resolving; compare with Windows CI.
Do not disable typechecking or add `librt` to dependencies.

## State-file reading

| File | Success | Failure |
|---|---|---|
| `.edi/runtimes/<provider>/<profile>/install-state.json` | `status: READY` | `status: FAILED` + `error_code` |
| `.edi/models/paddle-ocr/<model_id>/model-state.json` | `status: WARMED`, storage `UPSTREAM_CACHE` (not offline-pinned) | warm/integrity error codes above |

Installer stdout/stderr is intentionally not persisted (package-manager output can
contain sensitive repository information) — use the interactive run output for detail.

## Verification after any fix

```text
python -m pytest
edi doctor
edi providers list
edi models list
edi models verify pp-ocrv6-medium
```

Then re-walk `INSTALLATION.md` §11.

## See also

- [Installation quickstart](installation.md)
- [CLI reference](cli-reference.md)
- [Day-to-day operations](operations.md)
