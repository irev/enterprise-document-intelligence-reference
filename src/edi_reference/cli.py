"""Portable management CLI for runtime capability installation."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class HostInfo:
    os: str
    architecture: str
    docker: bool
    nvidia_smi: bool


_PROVIDERS = {
    "paddle-ocr": ("cpu", "nvidia"),
    "qwen25-vl-7b": ("cpu", "nvidia", "quantized"),
    "qwen25-vl-3b": ("cpu", "nvidia"),
    "docling": ("cpu", "accelerator"),
    "surya": ("cpu", "nvidia", "mps"),
}


def inspect_host() -> HostInfo:
    return HostInfo(
        os=platform.system().lower(),
        architecture=platform.machine().lower(),
        docker=shutil.which("docker") is not None,
        nvidia_smi=shutil.which("nvidia-smi") is not None,
    )


def _nvidia_summary() -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def resolve_install(provider: str, profile: str, host: HostInfo) -> dict[str, object]:
    profiles = _PROVIDERS.get(provider)
    if profiles is None:
        raise ValueError("UNKNOWN_PROVIDER")
    if profile not in profiles:
        raise ValueError("UNSUPPORTED_PROVIDER_PROFILE")
    if profile == "nvidia" and not host.nvidia_smi:
        raise ValueError("NVIDIA_RUNTIME_NOT_DETECTED")
    if profile == "mps" and host.os != "darwin":
        raise ValueError("MPS_REQUIRES_MACOS")
    return {
        "provider": provider,
        "profile": profile,
        "host": asdict(host),
        "execution": "isolated-runtime",
        "status": "PLANNED",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edi")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("doctor")

    providers = commands.add_parser("providers")
    provider_commands = providers.add_subparsers(dest="provider_command", required=True)
    provider_commands.add_parser("list")

    install = commands.add_parser("install")
    install.add_argument("--provider", required=True, choices=sorted(_PROVIDERS))
    install.add_argument("--profile", required=True)
    install.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    host = inspect_host()

    if args.command == "doctor":
        payload = asdict(host)
        payload["nvidia_gpu"] = _nvidia_summary()
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "providers":
        for provider, profiles in _PROVIDERS.items():
            print(f"{provider}: {', '.join(profiles)}")
        return 0

    if args.command == "install":
        try:
            plan = resolve_install(args.provider, args.profile, host)
        except ValueError as exc:
            print(str(exc))
            return 2
        if not args.dry_run:
            print("INSTALL_EXECUTION_NOT_IMPLEMENTED_USE_DRY_RUN")
            return 2
        print(json.dumps(plan, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
