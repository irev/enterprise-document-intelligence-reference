"""Code-owned bootstrap for local server installs (stdlib only, no shell).

Executed as an argv step from a trusted install plan::

    python -m edi_reference.application.server_bootstrap ollama <dest-dir>

The only inputs are the validated server identifier and a destination directory
resolved by the server — no client-supplied URLs, no shell strings. The download
URL is code-owned and pinned to the official vendor release location. The vendor
ships Linux archives as ``.tar.zst`` (zstandard); extraction uses Python's native
tarfile support where available and otherwise the system ``zstd`` binary via a
trusted argv (never a shell), failing closed when neither is available.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

OLLAMA_LINUX_URLS: dict[str, str] = {
    "x86_64": "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst",
    "amd64": "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-amd64.tar.zst",
    "aarch64": "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64.tar.zst",
    "arm64": "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-arm64.tar.zst",
}

_DOWNLOAD_CHUNK = 256 * 1024
_DOWNLOAD_TIMEOUT = 600
_ZSTD_TIMEOUT = 600


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "edi-bootstrap/1.0"})
    with urllib.request.urlopen(request, timeout=_DOWNLOAD_TIMEOUT) as response:
        with destination.open("wb") as handle:
            while True:
                chunk = response.read(_DOWNLOAD_CHUNK)
                if not chunk:
                    break
                handle.write(chunk)


def _extract_tar_zst(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, "r:*") as bundle:
            bundle.extractall(destination, filter="data")
        return
    except (ValueError, tarfile.TarError):
        pass
    zstd = shutil.which("zstd")
    if zstd is None:
        raise RuntimeError("ZSTD_NOT_AVAILABLE")
    tar_path = archive.with_suffix("")
    subprocess.run(
        [zstd, "-d", "-f", "-k", str(archive)],
        check=True,
        capture_output=True,
        timeout=_ZSTD_TIMEOUT,
    )
    with tarfile.open(tar_path, "r:") as bundle:
        bundle.extractall(destination, filter="data")


def extract_archive(archive: Path, destination: Path) -> None:
    if archive.name.endswith(".zst"):
        _extract_tar_zst(archive, destination)
        return
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(destination, filter="data")


def install_ollama_linux(destination: Path) -> None:
    machine = platform.machine().lower()
    url = OLLAMA_LINUX_URLS.get(machine)
    if url is None:
        raise RuntimeError(f"UNSUPPORTED_ARCHITECTURE:{machine}")
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ollama-", dir=destination) as scratch:
        archive = Path(scratch) / "ollama-linux.tar.zst"
        download(url, archive)
        extract_archive(archive, destination)
    if not (destination / "bin" / "ollama").is_file():
        raise RuntimeError("OLLAMA_BINARY_MISSING")


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "ollama":
        print("usage: python -m edi_reference.application.server_bootstrap ollama <dest-dir>")
        return 2
    try:
        install_ollama_linux(Path(argv[1]))
    except RuntimeError as exc:
        print(str(exc))
        return 1
    except (OSError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(f"BOOTSTRAP_FAILED:{exc.__class__.__name__}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
