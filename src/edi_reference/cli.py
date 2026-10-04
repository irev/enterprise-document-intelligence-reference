"""Portable management CLI for runtime capability installation."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

from edi_reference.application.provider_manifest import load_provider_manifest
from edi_reference.application.runtime_management import RuntimeManagementService


@dataclass(frozen=True, slots=True)
class HostInfo:
    os: str
    architecture: str
    docker: bool
    nvidia_smi: bool
    nvidia_driver_version: tuple[int, int, int] | None = None


def _nvidia_query(field: str) -> str | None:
    executable = shutil.which("nvidia-smi")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, f"--query-gpu={field}", "--format=csv,noheader"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip().splitlines()
    return value[0].strip() if result.returncode == 0 and value else None


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    try:
        parts = [int(part) for part in value.split(".")[:3]]
    except ValueError:
        return None
    return tuple((parts + [0, 0, 0])[:3])  # type: ignore[return-value]


def inspect_host() -> HostInfo:
    driver = _parse_version(_nvidia_query("driver_version"))
    return HostInfo(
        os=platform.system().lower(),
        architecture=platform.machine().lower(),
        docker=shutil.which("docker") is not None,
        nvidia_smi=shutil.which("nvidia-smi") is not None,
        nvidia_driver_version=driver,
    )


def resolve_install(provider: str, profile: str, host: HostInfo) -> dict[str, object]:
    service = RuntimeManagementService(load_provider_manifest())
    return service.plan_install(provider_id=provider, profile=profile, host=host)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edi")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")

    providers = commands.add_parser("providers")
    provider_commands = providers.add_subparsers(dest="provider_command", required=True)
    provider_commands.add_parser("list")

    models = commands.add_parser("models")
    model_commands = models.add_subparsers(dest="model_command", required=True)
    model_commands.add_parser("list")

    install = commands.add_parser("install")
    install.add_argument("--provider", required=True)
    install.add_argument("--profile", required=True)
    install.add_argument("--dry-run", action="store_true")
    install.add_argument("--yes", action="store_true")
    install.add_argument("--runtime-root", type=Path, default=Path(".edi/runtimes"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    host = inspect_host()

    if args.command == "doctor":
        payload = asdict(host)
        payload["nvidia_gpu"] = _nvidia_query("name,memory.total")
        print(json.dumps(payload, indent=2))
        return 0

    service = RuntimeManagementService(load_provider_manifest())
    if args.command == "providers":
        for provider in service.providers():
            profiles = provider["profiles"]
            assert isinstance(profiles, list)
            print(f"{provider['provider_id']}: {', '.join(str(item) for item in profiles)}")
        return 0

    if args.command == "models":
        for model in service.models():
            print(f"{model['provider_id']}: {model['model_id']}")
        return 0

    if args.command == "install":
        try:
            service = RuntimeManagementService(load_provider_manifest())
            runtime_dir = args.runtime_root / args.provider / args.profile
            from edi_reference.application.runtime_installer import ensure_runtime_venv
            python_executable = str(runtime_dir / "venv" / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python"))
            plan = service.plan_install(
                provider_id=args.provider,
                profile=args.profile,
                host=host,
                python_executable=python_executable,
            )
        except ValueError as exc:
            print(str(exc))
            return 2
        if args.dry_run:
            print(json.dumps(plan, indent=2))
            return 0
        if not args.yes:
            print("INSTALL_CONFIRMATION_REQUIRED_USE_YES")
            return 2
        try:
            result = service.install_provider(
                provider_id=args.provider,
                profile=args.profile,
                host=host,
                runtime_root=args.runtime_root,
            )
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            print(str(exc))
            return 2
        print(json.dumps(asdict(result), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
