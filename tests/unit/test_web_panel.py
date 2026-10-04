import json
import threading
from http.client import HTTPConnection
from pathlib import Path

from edi_reference.adapters.web_panel import build_server, handle_request
from edi_reference.application.runtime_bootstrap import HostCapabilities, PythonInterpreter
from edi_reference.application.runtime_installer import InstallExecutionResult, StepResult
from edi_reference.cli import HostInfo, main, run_api_request


def _call(
    method: str,
    path: str,
    *,
    body: bytes = b"",
    api=None,  # type: ignore[no-untyped-def]
    runtime_root: str = ".edi/runtimes",
):
    if api is None:

        def api(text: str):  # type: ignore[no-redef]
            return {"ok": True, "operation": None, "result": {}}, 0

    return handle_request(
        method, path, body, api=api, runtime_root=runtime_root
    )


def _post(path: str, payload: dict, api=None) -> tuple[int, dict]:  # type: ignore[no-untyped-def]
    status, _, data = _call(
        "POST", path, body=json.dumps(payload).encode("utf-8"), api=api
    )
    return status, json.loads(data)


def _patch_install_host(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host",
        lambda: HostInfo("linux", "x86_64", False, False),
    )
    monkeypatch.setattr(
        "edi_reference.cli.inspect_host_capabilities",
        lambda **_: HostCapabilities(
            os="linux",
            architecture="x86_64",
            python_interpreters=(
                PythonInterpreter(Path("/usr/bin/python3"), (3, 12, 0)),
            ),
            nvidia=False,
            nvidia_driver_version=None,
        ),
    )


def _recording_api(record: list, *, error: str | None = None):  # type: ignore[no-untyped-def]
    def api(text: str):  # type: ignore[no-untyped-def]
        request = json.loads(text)
        record.append(request)
        if error is not None:
            return {"ok": False, "operation": request["operation"], "error": {"code": error}}, 2
        return {"ok": True, "operation": request["operation"], "result": {"x": 1}}, 0

    return api


# --- routing ---------------------------------------------------------------------


def test_index_serves_html() -> None:
    status, content_type, data = _call("GET", "/")

    assert status == 200
    assert content_type.startswith("text/html")
    assert b"EDI Runtime Panel" in data


def test_host_endpoint_delegates_to_doctor_operation() -> None:
    record: list = []

    status, _, data = _call("GET", "/admin/runtime/host", api=_recording_api(record))

    assert status == 200
    assert record == [{"operation": "doctor", "params": {}}]
    assert json.loads(data)["ok"] is True


def test_providers_and_models_endpoints() -> None:
    for path, operation in (
        ("/admin/runtime/providers", "providers.list"),
        ("/admin/runtime/models", "models.list"),
    ):
        record: list = []
        status, _, _ = _call("GET", path, api=_recording_api(record))

        assert status == 200
        assert record[0]["operation"] == operation


def test_install_plan_post_passes_identifiers_only() -> None:
    record: list = []

    status, _, data = _call(
        "POST",
        "/admin/runtime/providers/paddle-ocr/install-plans",
        body=json.dumps({"profile": "nvidia", "confirm": True, "command": "rm -rf"}).encode(),
        api=_recording_api(record),
        runtime_root="/rt",
    )

    assert status == 200
    assert record == [
        {
            "operation": "install.plan",
            "params": {
                "provider_id": "paddle-ocr",
                "profile": "nvidia",
                "runtime_root": "/rt",
            },
        }
    ]
    assert json.loads(data)["ok"] is True


def test_install_plan_requires_profile() -> None:
    record: list = []

    status, _, data = _call(
        "POST",
        "/admin/runtime/providers/paddle-ocr/install-plans",
        body=b"{}",
        api=_recording_api(record),
    )

    assert status == 400
    assert json.loads(data)["error"]["code"] == "INVALID_PARAMS"
    assert record == []


def test_install_plan_rejects_malformed_json() -> None:
    status, _, data = _call(
        "POST",
        "/admin/runtime/providers/paddle-ocr/install-plans",
        body=b"{not json",
    )

    assert status == 400
    assert json.loads(data)["error"]["code"] == "INVALID_REQUEST"


def test_reserved_verify_routes_fail_closed() -> None:
    record: list = []
    for path in (
        "/admin/runtime/providers/paddle-ocr/verify",
        "/admin/runtime/models/pp-ocrv6-medium/verify",
    ):
        status, _, data = _call(
            "POST", path, body=b'{"profile": "cpu"}', api=_recording_api(record)
        )

        assert status == 403
        assert json.loads(data)["error"]["code"] == "RESERVED_OPERATION"
    assert record == []


# --- confirm-gated execution routes ---------------------------------------------


def test_install_execute_requires_confirm() -> None:
    record: list = []

    status, payload = _post(
        "/admin/runtime/providers/paddle-ocr/install",
        {"profile": "cpu"},
        api=_recording_api(record),
    )

    assert status == 400
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert record == []


def test_install_execute_with_confirm_runs(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _patch_install_host(monkeypatch)
    captured: dict[str, object] = {}

    def fake_install(self, **kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return InstallExecutionResult(
            provider_id=kwargs["provider_id"],
            profile=kwargs["profile"],
            runtime_dir="runtime",
            status="READY",
            steps=(StepResult("install", 0),),
        )

    monkeypatch.setattr(
        "edi_reference.application.runtime_management.RuntimeManagementService.install_provider",
        fake_install,
    )

    status, payload = _post(
        "/admin/runtime/providers/paddle-ocr/install",
        {"profile": "cpu", "confirm": True, "command": "rm -rf /"},
        api=run_api_request,
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["result"]["status"] == "READY"
    assert captured["provider_id"] == "paddle-ocr"
    assert captured["profile"] == "cpu"
    assert "confirm" not in captured
    assert "command" not in captured


def test_model_pull_requires_confirm() -> None:
    record: list = []

    status, payload = _post(
        "/admin/runtime/models/pp-ocrv6-medium/pull",
        {"profile": "cpu"},
        api=_recording_api(record),
    )

    assert status == 400
    assert payload["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert record == []


def test_model_pull_with_confirm_dispatches(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    def fake_pull(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return {"model_id": kwargs["model_id"], "status": "WARMED"}

    monkeypatch.setattr("edi_reference.cli._pull_model", fake_pull)

    status, payload = _post(
        "/admin/runtime/models/pp-ocrv6-medium/pull",
        {"confirm": True},
        api=run_api_request,
    )

    assert status == 200
    assert payload["ok"] is True
    assert payload["result"]["status"] == "WARMED"
    assert captured["model_id"] == "pp-ocrv6-medium"
    assert captured["profile"] == "cpu"
    assert "confirm" not in captured


def test_install_execute_wrong_method_is_405() -> None:
    status, _, _ = _call(
        "GET", "/admin/runtime/providers/paddle-ocr/install"
    )

    assert status == 405


def test_unknown_path_is_404() -> None:
    status, _, data = _call("GET", "/admin/runtime/secrets")

    assert status == 404
    assert json.loads(data)["error"]["code"] == "NOT_FOUND"


def test_wrong_method_is_405() -> None:
    status_get_plan, _, _ = _call(
        "GET", "/admin/runtime/providers/paddle-ocr/install-plans"
    )
    status_put, _, _ = _call("PUT", "/admin/runtime/models")

    assert status_get_plan == 405
    assert status_put == 405


def test_api_error_is_propagated() -> None:
    status, _, data = _call(
        "GET", "/admin/runtime/host", api=_recording_api([], error="RUNTIME_INCOMPATIBLE")
    )

    assert status == 400
    assert json.loads(data)["error"]["code"] == "RUNTIME_INCOMPATIBLE"


def test_read_only_routes_call_real_api() -> None:
    status, _, data = _call("GET", "/admin/runtime/models", api=run_api_request)

    assert status == 200
    payload = json.loads(data)
    assert payload["ok"] is True
    assert any(
        model["model_id"] == "pp-ocrv6-medium" for model in payload["result"]["models"]
    )


# --- real loopback server --------------------------------------------------------


def test_serves_request_over_loopback() -> None:
    server = build_server(
        "127.0.0.1", 0, api=_recording_api([]), runtime_root=".edi/runtimes"
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        connection.request("GET", "/admin/runtime/providers")
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()

        assert response.status == 200
        assert payload["ok"] is True
        assert response.getheader("Cache-Control") == "no-store"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# --- edi web CLI wiring ----------------------------------------------------------


def test_edi_web_starts_and_stops(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class _FakeServer:
        server_address = ("127.0.0.1", 4099)

        def serve_forever(self) -> None:
            captured["served"] = True

        def server_close(self) -> None:
            captured["closed"] = True

    def fake_build(host: str, port: int, *, api, runtime_root: str):  # type: ignore[no-untyped-def]
        captured.update(host=host, port=port, api=api, runtime_root=runtime_root)
        return _FakeServer()

    monkeypatch.setattr("edi_reference.cli.build_server", fake_build)

    code = main(["web", "--port", "4099", "--hostname", "0.0.0.0"])

    assert code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 4099
    assert captured["api"] is run_api_request
    assert captured["served"] is True
    assert captured["closed"] is True
    out = capsys.readouterr().out
    assert "http://0.0.0.0:4099/" in out
    assert "read-only" in out


def test_edi_web_defaults_to_loopback(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class _FakeServer:
        server_address = ("127.0.0.1", 4099)

        def serve_forever(self) -> None:
            pass

        def server_close(self) -> None:
            pass

    def fake_build(host: str, port: int, *, api, runtime_root: str):  # type: ignore[no-untyped-def]
        captured.update(host=host, port=port)
        return _FakeServer()

    monkeypatch.setattr("edi_reference.cli.build_server", fake_build)

    code = main(["web"])

    assert code == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 4099
    assert "http://127.0.0.1:4099/" in capsys.readouterr().out
