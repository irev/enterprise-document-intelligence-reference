from pathlib import Path
from unittest.mock import Mock

from edi_reference.adapters.host_capabilities import discover_python_interpreters


def test_python_discovery_records_actual_version(monkeypatch) -> None:
    monkeypatch.setattr("edi_reference.adapters.host_capabilities.sys.executable", "/python/current")
    monkeypatch.setattr(
        "edi_reference.adapters.host_capabilities.shutil.which",
        lambda name: "/python/312" if name == "python3.12" else None,
    )

    def run(argv, **kwargs):
        version = "3.12.9" if argv[0] == str(Path("/python/312").resolve()) else "3.14.1"
        return Mock(returncode=0, stdout=version + "\n", stderr="")

    monkeypatch.setattr("edi_reference.adapters.host_capabilities.subprocess.run", run)

    result = discover_python_interpreters()

    assert {item.version for item in result} == {(3, 14, 1), (3, 12, 9)}
