import tarfile
from pathlib import Path

from edi_reference.application import server_bootstrap


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int) -> bytes:
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk


def _make_tar_gz(path: Path, member: str, content: bytes) -> None:
    with tarfile.open(path, "w:gz") as bundle:
        source = path.parent / "member.bin"
        source.write_bytes(content)
        bundle.add(source, arcname=member)
    (path.parent / "member.bin").unlink()


def _make_tar(path: Path, member: str, content: bytes) -> None:
    with tarfile.open(path, "w") as bundle:
        source = path.parent / "member.bin"
        source.write_bytes(content)
        bundle.add(source, arcname=member)
    (path.parent / "member.bin").unlink()


# --- download (code-owned URL, no client input) --------------------------------


def test_download_requests_code_owned_url_with_user_agent(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    seen: dict[str, object] = {}

    def fake_urlopen(request, timeout=None):  # type: ignore[no-untyped-def]
        seen["url"] = request.full_url
        seen["user_agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        return _FakeResponse(b"abc")

    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.urllib.request.urlopen",
        fake_urlopen,
    )

    server_bootstrap.download(
        server_bootstrap.OLLAMA_LINUX_URLS["x86_64"], tmp_path / "a.bin"
    )

    assert seen["url"] == (
        "https://github.com/ollama/ollama/releases/latest/download/"
        "ollama-linux-amd64.tar.zst"
    )
    assert seen["user_agent"] == "edi-bootstrap/1.0"
    assert isinstance(seen["timeout"], int)
    assert (tmp_path / "a.bin").read_bytes() == b"abc"


def test_url_map_is_code_owned_and_arch_specific() -> None:
    urls = server_bootstrap.OLLAMA_LINUX_URLS
    assert set(urls) == {"x86_64", "amd64", "aarch64", "arm64"}
    assert urls["x86_64"].endswith("ollama-linux-amd64.tar.zst")
    assert urls["aarch64"].endswith("ollama-linux-arm64.tar.zst")
    for url in urls.values():
        assert url.startswith("https://github.com/ollama/ollama/releases/")


# --- extraction ---------------------------------------------------------------


def test_extract_archive_gz_extracts_members(tmp_path) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "bundle.tgz"
    _make_tar_gz(archive, "bin/tool", b"payload")
    destination = tmp_path / "dest"
    destination.mkdir()

    server_bootstrap.extract_archive(archive, destination)

    assert (destination / "bin" / "tool").read_bytes() == b"payload"


def test_extract_tar_zst_uses_zstd_binary_argv(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "bundle.tar.zst"
    archive.write_bytes(b"not-really-zstd")
    tar_path = tmp_path / "bundle.tar"
    _make_tar(tar_path, "bin/ollama", b"binary")
    destination = tmp_path / "dest"
    destination.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(list(argv))
        import subprocess

        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.shutil.which",
        lambda name: "/usr/bin/zstd" if name == "zstd" else None,
    )
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.subprocess.run", fake_run
    )

    server_bootstrap.extract_archive(archive, destination)

    assert calls == [["/usr/bin/zstd", "-d", "-f", "-k", str(archive)]]
    assert (destination / "bin" / "ollama").read_bytes() == b"binary"


def test_extract_tar_zst_without_zstd_fails_closed(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    archive = tmp_path / "bundle.tar.zst"
    archive.write_bytes(b"x")
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.shutil.which",
        lambda name: None,
    )

    try:
        server_bootstrap.extract_archive(archive, tmp_path)
    except RuntimeError as exc:
        assert str(exc) == "ZSTD_NOT_AVAILABLE"
    else:
        raise AssertionError("expected ZSTD_NOT_AVAILABLE")


# --- install_ollama_linux ------------------------------------------------------


def test_install_ollama_linux_happy_path(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    seen: dict[str, str] = {}

    def fake_download(url: str, destination: Path) -> None:
        seen["url"] = url
        destination.write_bytes(b"stub")

    def fake_extract(archive: Path, destination: Path) -> None:
        binary_dir = destination / "bin"
        binary_dir.mkdir(parents=True, exist_ok=True)
        (binary_dir / "ollama").write_bytes(b"#!/bin/sh\n")

    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.platform.machine",
        lambda: "x86_64",
    )
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.download", fake_download
    )
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.extract_archive", fake_extract
    )

    destination = tmp_path / "native"
    server_bootstrap.install_ollama_linux(destination)

    assert seen["url"].endswith("ollama-linux-amd64.tar.zst")
    assert (destination / "bin" / "ollama").is_file()


def test_install_ollama_linux_missing_binary_fails(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.platform.machine",
        lambda: "x86_64",
    )
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.download",
        lambda url, destination: destination.write_bytes(b"stub"),
    )
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.extract_archive",
        lambda archive, destination: None,
    )

    try:
        server_bootstrap.install_ollama_linux(tmp_path / "native")
    except RuntimeError as exc:
        assert str(exc) == "OLLAMA_BINARY_MISSING"
    else:
        raise AssertionError("expected OLLAMA_BINARY_MISSING")


def test_install_ollama_linux_rejects_unknown_arch(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.application.server_bootstrap.platform.machine",
        lambda: "riscv64",
    )

    try:
        server_bootstrap.install_ollama_linux(tmp_path / "native")
    except RuntimeError as exc:
        assert str(exc) == "UNSUPPORTED_ARCHITECTURE:riscv64"
    else:
        raise AssertionError("expected UNSUPPORTED_ARCHITECTURE")


# --- main ----------------------------------------------------------------------


def test_main_requires_exact_ollama_invocation() -> None:
    assert server_bootstrap.main([]) == 2
    assert server_bootstrap.main(["vllm", "/tmp/x"]) == 2
    assert server_bootstrap.main(["ollama"]) == 2


def test_main_reports_runtime_error_code(capsys) -> None:  # type: ignore[no-untyped-def]
    def failing(destination: Path) -> None:
        raise RuntimeError("ZSTD_NOT_AVAILABLE")

    original = server_bootstrap.install_ollama_linux
    server_bootstrap.install_ollama_linux = failing  # type: ignore[assignment]
    try:
        code = server_bootstrap.main(["ollama", "/tmp/dest"])
    finally:
        server_bootstrap.install_ollama_linux = original  # type: ignore[assignment]

    assert code == 1
    assert "ZSTD_NOT_AVAILABLE" in capsys.readouterr().out
