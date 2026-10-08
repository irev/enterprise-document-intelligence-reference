"""Local web panel over the shared runtime-management operations.

Stdlib only (``http.server``); no framework dependency. Routes mirror
``docs/RUNTIME-CONTROL-PLANE.md``: read-only views
(``GET /admin/runtime/{host,providers,models,status,servers}`` plus
``GET /admin/runtime/servers/recommendations``), plan
(``POST /admin/runtime/providers/{id}/install-plans``,
``POST /admin/runtime/servers/{id}/install-plans``), and confirm-gated
execution (``POST .../install``, ``POST .../pull`` with ``{"confirm": true}`` —
equivalent of ``--yes``). Verify routes answer ``403 RESERVED_OPERATION``.
Every route delegates to the same stdio API operation used by ``tlkdoc api`` —
never a second implementation, never an executable path or shell string from
the client. Views render only data returned by those operations; there is no
mock or placeholder content.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

MAX_BODY_BYTES = 65_536

ApiRunner = Callable[[str], tuple[dict[str, object], int]]

JSON_TYPE = "application/json; charset=utf-8"
HTML_TYPE = "text/html; charset=utf-8"


def _envelope(code: str) -> dict[str, object]:
    return {"ok": False, "operation": None, "error": {"code": code}}


def _status_for(payload: dict[str, object]) -> int:
    if payload.get("ok") is True:
        return 200
    error = payload.get("error")
    code = error.get("code") if isinstance(error, dict) else None
    if code == "INTERNAL_ERROR":
        return 500
    return 400


def _json_body(body: bytes) -> dict[str, object]:
    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("INVALID_REQUEST") from exc
    if not isinstance(parsed, dict):
        raise ValueError("INVALID_REQUEST")
    return parsed


def handle_request(
    method: str,
    path: str,
    body: bytes,
    *,
    api: ApiRunner,
    runtime_root: str,
) -> tuple[int, str, bytes]:
    """Route one HTTP request to a shared API operation; returns (status, content_type, data)."""
    route = urlparse(path).path.rstrip("/") or "/"
    if method not in {"GET", "POST"}:
        return 405, JSON_TYPE, json.dumps(_envelope("METHOD_NOT_ALLOWED")).encode(
            "utf-8"
        )

    if method == "GET" and route == "/":
        return 200, HTML_TYPE, PANEL_HTML.encode("utf-8")

    target = _action_route(route)
    if target is not None:
        kind, subject, action = target
        if action == "verify":
            return 403, JSON_TYPE, json.dumps(
                _envelope("RESERVED_OPERATION")
            ).encode("utf-8")
        if method != "POST":
            return 405, JSON_TYPE, json.dumps(_envelope("METHOD_NOT_ALLOWED")).encode(
                "utf-8"
            )
        try:
            request_body = _json_body(body)
        except ValueError as exc:
            return 400, JSON_TYPE, json.dumps(_envelope(str(exc))).encode("utf-8")
        return _execute_action(
            kind, subject, action, request_body, api=api, runtime_root=runtime_root
        )

    read_only = {
        "GET": {
            "/admin/runtime/host": "doctor",
            "/admin/runtime/providers": "providers.list",
            "/admin/runtime/models": "models.list",
            "/admin/runtime/status": "status.summary",
            "/admin/runtime/servers": "serve.list",
            "/admin/runtime/servers/recommendations": "serve.recommend",
        }
    }
    operation = read_only.get(method, {}).get(route)
    if operation is None:
        known_post = {
            "/admin/runtime/host",
            "/admin/runtime/providers",
            "/admin/runtime/models",
            "/admin/runtime/status",
            "/admin/runtime/servers",
            "/admin/runtime/servers/recommendations",
        }
        if route in known_post:
            return 405, JSON_TYPE, json.dumps(_envelope("METHOD_NOT_ALLOWED")).encode(
                "utf-8"
            )
        return 404, JSON_TYPE, json.dumps(_envelope("NOT_FOUND")).encode("utf-8")
    params: dict[str, object] = (
        {"runtime_root": runtime_root} if operation == "status.summary" else {}
    )
    payload, _ = api(json.dumps({"operation": operation, "params": params}))
    return _status_for(payload), JSON_TYPE, json.dumps(payload).encode("utf-8")


def _action_route(route: str) -> tuple[str, str, str] | None:
    """Map /admin/runtime/{providers|models|servers}/{subject}/{action} to (kind, subject, action)."""
    segments = [segment for segment in route.split("/") if segment]
    if len(segments) != 5 or segments[:2] != ["admin", "runtime"]:
        return None
    kind, subject, action = segments[2], segments[3], segments[4]
    if kind == "providers" and action in {"install", "install-plans", "verify"}:
        return kind, subject, action
    if kind == "models" and action in {"pull", "verify"}:
        return kind, subject, action
    if kind == "servers" and action in {"install", "install-plans", "verify"}:
        return kind, subject, action
    return None


def _execute_action(
    kind: str,
    subject: str,
    action: str,
    request_body: dict[str, object],
    *,
    api: ApiRunner,
    runtime_root: str,
) -> tuple[int, str, bytes]:
    """Dispatch a confirm-gated execution route to its shared API operation."""
    if kind == "servers":
        server_params: dict[str, object] = {
            "server_id": subject,
            "runtime_root": runtime_root,
        }
        for key in ("via", "model", "gpu", "variant"):
            if key in request_body:
                server_params[key] = request_body[key]
        if action == "install-plans":
            operation = "serve.plan"
        else:  # servers install — confirm-gated execution
            if request_body.get("confirm") is not True:
                return 400, JSON_TYPE, json.dumps(_envelope("CONFIRMATION_REQUIRED")).encode(
                    "utf-8"
                )
            operation = "serve.execute"
            server_params["confirm"] = True
        payload, _ = api(json.dumps({"operation": operation, "params": server_params}))
        return _status_for(payload), JSON_TYPE, json.dumps(payload).encode("utf-8")

    profile = request_body.get("profile", "cpu" if kind == "models" else None)
    if not isinstance(profile, str) or not profile:
        return 400, JSON_TYPE, json.dumps(_envelope("INVALID_PARAMS")).encode("utf-8")

    if action == "install-plans":
        operation = "install.plan"
        params: dict[str, object] = {
            "provider_id": subject,
            "profile": profile,
            "runtime_root": runtime_root,
        }
    elif action == "install":
        if request_body.get("confirm") is not True:
            return 400, JSON_TYPE, json.dumps(_envelope("CONFIRMATION_REQUIRED")).encode(
                "utf-8"
            )
        operation = "install.execute"
        params = {
            "provider_id": subject,
            "profile": profile,
            "confirm": True,
            "runtime_root": runtime_root,
        }
    else:  # models pull
        if request_body.get("confirm") is not True:
            return 400, JSON_TYPE, json.dumps(_envelope("CONFIRMATION_REQUIRED")).encode(
                "utf-8"
            )
        operation = "models.pull"
        params = {
            "model_id": subject,
            "profile": profile,
            "confirm": True,
            "runtime_root": runtime_root,
        }
    payload, _ = api(json.dumps({"operation": operation, "params": params}))
    return _status_for(payload), JSON_TYPE, json.dumps(payload).encode("utf-8")


class _PanelHandler(BaseHTTPRequestHandler):
    """HTTP adapter delegating every route to ``handle_request``."""

    api: ApiRunner
    runtime_root: str
    server_version = "edi-panel"

    def _respond(self, method: str) -> None:
        body = b""
        if method == "POST":
            length_text = self.headers.get("Content-Length", "0")
            try:
                length = int(length_text)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY_BYTES:
                payload = json.dumps(_envelope("INVALID_REQUEST")).encode("utf-8")
                self._send(400, JSON_TYPE, payload)
                return
            body = self.rfile.read(length) if length else b""
        status, content_type, data = handle_request(
            method,
            self.path,
            body,
            api=self.api,
            runtime_root=self.runtime_root,
        )
        self._send(status, content_type, data)

    def _send(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        self._respond("GET")

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        self._respond("POST")

    def log_message(self, format: str, *args: object) -> None:
        pass


def build_server(
    host: str,
    port: int,
    *,
    api: ApiRunner,
    runtime_root: str,
) -> ThreadingHTTPServer:
    """Create the panel server bound to ``host:port`` (port 0 picks a free port)."""
    handler = type(
        "PanelHandler",
        (_PanelHandler,),
        {"api": staticmethod(api), "runtime_root": runtime_root},
    )
    return ThreadingHTTPServer((host, port), handler)


PANEL_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EDI Runtime Control Panel</title>
<style>
:root {
  --vellum: #f7f5fb; --vellum-dark: #ece9f3; --bg-elevated: #fffefe;
  --ink: #292439; --ink-muted: #514b60; --ink-faint: #696477;
  --border: #cfc9d9; --border-light: #ddd8e6;
  --iron-gall: #292439; --iron-gall-hover: #433a57;
  --vermillion: #a34850; --vermillion-hover: #893840; --vermillion-faint: #f6e7e9;
  --gold: #94653d; --focus: #8059a0;
  --green: #376b59; --green-bg: #e7f3ed; --green-border: #c6e4d5;
  --font-display: 'Fraunces', Georgia, 'Times New Roman', serif;
  --font-body: 'DM Sans', 'Segoe UI', Arial, sans-serif;
  --font-mono: 'IBM Plex Mono', Consolas, 'Courier New', monospace;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0; min-width: 320px; background: var(--vellum); color: var(--ink);
  font: 400 1rem/1.6 var(--font-body); -webkit-font-smoothing: antialiased;
}
h1, h2 { margin: 0; font-family: var(--font-display); font-weight: 500; line-height: 1.2; }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }
code { font-family: var(--font-mono); font-size: .85em; background: var(--vellum-dark);
       padding: 1px 5px; border-radius: 5px; }

.app-header {
  height: 72px; display: flex; align-items: center; justify-content: space-between;
  gap: 16px; padding: 0 28px; background: var(--bg-elevated);
  border-bottom: 1px solid var(--border-light);
}
.brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-mark {
  width: 42px; height: 42px; flex: none; display: grid; place-items: center;
  border-radius: 13px; background: var(--iron-gall); color: #fff;
  font: 500 1.45rem/1 var(--font-display); letter-spacing: -.07em;
}
.brand-copy { display: flex; flex-direction: column; line-height: 1.12; min-width: 0; }
.brand-name { font: 600 1.22rem/1.1 var(--font-display); letter-spacing: -.025em; }
.brand-caption { margin-top: 3px; color: var(--ink-muted); font-size: .68rem; letter-spacing: .02em; }
.pill {
  display: inline-flex; align-items: center; gap: 8px; flex: none; padding: 7px 11px;
  color: var(--green); background: var(--green-bg); border: 1px solid var(--green-border);
  border-radius: 99px; font: 500 .72rem/1.2 var(--font-mono);
}
.pill-dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }

.page { padding: clamp(22px, 3vw, 42px); }
.inner { width: min(100%, 980px); margin-inline: auto; }
.eyebrow {
  margin: 0 0 6px; color: var(--vermillion);
  font: 600 .7rem/1.4 var(--font-mono); letter-spacing: .08em; text-transform: uppercase;
}
.page h1 { font-size: clamp(1.5rem, 2.4vw, 2rem); letter-spacing: -.04em; }
.lede { margin: 8px 0 24px; color: var(--ink-muted); font-size: .92rem; }

.grid {
  display: grid; gap: 15px;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
}
.card {
  min-width: 0; overflow: hidden; border: 1px solid var(--border-light);
  border-radius: 16px; background: #fff; box-shadow: 0 5px 22px rgba(43,33,60,.035);
  animation: fade-in 400ms cubic-bezier(.2,.7,.2,1) both;
}
.card--plan { grid-column: 1 / -1; }
.card-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 16px;
  padding: 21px 24px 18px; background: #fcfbfe;
}
.card-head h2 { font-size: 1.22rem; letter-spacing: -.015em; }
.card-head p { margin: 5px 0 0; color: var(--ink-muted); font-size: .8rem; line-height: 1.5; }
.badge {
  flex: none; padding: 4px 8px; border-radius: 6px; color: #6d4651;
  background: var(--vermillion-faint); font: 600 .66rem/1.35 var(--font-mono);
  text-transform: uppercase; letter-spacing: .04em;
}
.card-body { border-top: 1px solid var(--border-light); }
.facts { margin: 0; padding: 6px 0; }
.facts > div {
  display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  padding: 12px 24px; font-size: .82rem;
}
.facts > div + div { border-top: 1px solid #eeeaf3; }
.facts dt { color: var(--ink-muted); }
.facts dd {
  margin: 0; color: var(--ink); font-family: var(--font-mono); font-size: .78rem;
  text-align: right; overflow-wrap: anywhere;
}
.facts .is-empty { display: block; color: var(--ink-faint); font-style: italic; }

.field { display: grid; gap: 6px; color: var(--ink); font-size: .81rem; font-weight: 700; }
.field select, .field input {
  min-height: 44px; padding: 9px 12px; border: 1px solid #bfb7cb; border-radius: 9px;
  background: #fff; color: var(--ink); font: 400 .87rem/1.4 var(--font-body);
}
.field select:hover, .field input:hover { border-color: #82738f; }
.btn {
  min-height: 44px; padding: 0 18px; border: 0; border-radius: 10px; color: #fff;
  background: var(--vermillion); font: 700 .82rem/1 var(--font-body); cursor: pointer;
  transition: background 150ms cubic-bezier(.2,.7,.2,1);
}
.btn:hover { background: var(--vermillion-hover); }
.result {
  margin: 0; padding: 14px 24px 20px; border-top: 1px solid #eeeaf3;
  background: var(--vellum); color: var(--ink); white-space: pre-wrap;
  overflow-x: auto; font: 400 .78rem/1.5 var(--font-mono);
}
.result:empty { display: none; }
.note {
  margin: 22px 0 0; color: var(--ink-faint); font: .72rem/1.6 var(--font-mono);
}

.primary-nav {
  display: flex; align-items: center; gap: 5px; padding: 4px;
  background: var(--vellum-dark); border-radius: 13px;
}
.nav-item {
  min-height: 42px; padding: 6px 17px; border: 0; border-radius: 9px;
  background: transparent; color: var(--ink-muted); font-size: .85rem; font-weight: 600;
  cursor: pointer; transition: background 150ms, color 150ms, box-shadow 150ms;
}
.nav-item:hover { background: #e6e0ee; color: var(--ink); }
.nav-item.is-active { background: #fff; color: var(--ink); box-shadow: 0 2px 7px rgba(38,29,56,.12); }

.btn--secondary {
  color: var(--ink); background: #fff; border: 1px solid #c9c2d3;
}
.btn--secondary:hover:not(:disabled) { border-color: #81748f; background: #f4f1f8; }
.btn:disabled { opacity: .55; cursor: not-allowed; }

.install-form {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  align-items: end; gap: 14px; padding: 18px 24px 8px;
}
.install-actions {
  display: flex; justify-content: flex-end; gap: 9px; flex-wrap: wrap;
  padding: 6px 24px 18px;
}

.stage-list {
  margin: 0; padding: 4px 0 8px; border-top: 1px solid var(--border-light);
  list-style: none;
}
.stage-list[hidden] { display: none; }
.field[hidden] { display: none; }
.stage-list li {
  display: flex; align-items: center; gap: 11px; padding: 11px 24px;
  font-size: .82rem;
}
.stage-list li + li { border-top: 1px solid #eeeaf3; }
.stage-dot {
  width: 11px; height: 11px; flex: none; border-radius: 50%;
  background: var(--vellum-dark); border: 2px solid var(--border);
}
.stage-name { flex: 1; min-width: 0; color: var(--ink); font-weight: 600; }
.stage-state {
  color: var(--ink-faint); font: 600 .66rem/1.35 var(--font-mono);
  text-transform: uppercase; letter-spacing: .05em;
}
li.is-active .stage-dot {
  background: var(--vermillion); border-color: var(--vermillion);
  animation: pulse 1s ease-in-out infinite;
}
li.is-active .stage-state { color: var(--vermillion); }
li.is-done .stage-dot { background: var(--green); border-color: var(--green); }
li.is-done .stage-state { color: var(--green); }
li.is-failed .stage-dot { background: var(--vermillion-hover); border-color: var(--vermillion-hover); }
li.is-failed .stage-state { color: var(--vermillion-hover); }
li.is-skipped .stage-dot { background: var(--border); border-color: var(--border); }
li.is-skipped .stage-name { color: var(--ink-faint); font-weight: 400; }

.progress {
  display: none; height: 10px; margin: 4px 24px 16px; overflow: hidden;
  border-radius: 99px; background: var(--vellum-dark);
}
.progress.is-active { display: block; }
.progress-bar {
  height: 100%; width: 42%; border-radius: 99px;
  background: linear-gradient(90deg, var(--vermillion), var(--gold));
  animation: flow 1.15s cubic-bezier(.4,0,.6,1) infinite;
}
.progress.is-download .progress-bar {
  background: linear-gradient(90deg, var(--gold), var(--vermillion));
}
@keyframes fade-in { from { opacity: 0; transform: translateY(7px); } to { opacity: 1; transform: translateY(0); } }
@keyframes flow { from { transform: translateX(-110%); } to { transform: translateX(340%); } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }

@media (max-width: 640px) {
  .app-header { padding: 0 16px; }
  .brand-copy { display: none; }
  .install-form { grid-template-columns: 1fr; }
  .nav-item { min-height: 40px; padding: 5px 12px; font-size: .78rem; }
}
@media (prefers-reduced-motion: reduce) {
  .card { animation: none; }
  .progress-bar, li.is-active .stage-dot { animation: none; }
  .progress.is-active .progress-bar { width: 100%; opacity: .6; }
}
</style>
</head>
<body>
<header class="app-header">
  <div class="brand">
    <span class="brand-mark">E</span>
    <span class="brand-copy">
      <span class="brand-name">Enterprise Document Intelligence</span>
      <span class="brand-caption">Runtime Control Plane</span>
    </span>
  </div>
  <nav class="primary-nav" aria-label="Panel sections">
    <button type="button" class="nav-item is-active" data-view="overview">Overview</button>
    <button type="button" class="nav-item" data-view="servers">Servers</button>
    <button type="button" class="nav-item" data-view="install">Install</button>
  </nav>
  <span class="pill"><span class="pill-dot"></span>LOCAL &middot; CONFIRM-GATED</span>
</header>
<main class="page">
  <div class="inner">
    <section id="view-overview" class="view">
    <p class="eyebrow">Fleet Readout</p>
    <h1>Overview</h1>
    <p class="lede">Read-only host probe, VRAM tier, provider/model/server readiness,
      and catalog &mdash; every value is a live <code>edi</code> operation response.
      Execution lives on the Install and Servers pages, confirm-gated.</p>
    <div class="grid">
      <section class="card">
        <div class="card-head">
          <div><h2>Host</h2><p>Environment probe: OS, architecture, GPU visibility.</p></div>
          <span class="badge">doctor</span>
        </div>
        <div class="card-body"><dl class="facts" id="host"></dl></div>
      </section>
      <section class="card">
        <div class="card-head">
          <div><h2>Status</h2><p>Fleet readiness from <code>tlkdoc ps</code> &mdash;
            VRAM tier plus runtime, model, and server states.</p></div>
          <span class="badge">status.summary</span>
        </div>
        <div class="card-body"><dl class="facts" id="status"></dl></div>
      </section>
      <section class="card">
        <div class="card-head">
          <div><h2>Providers</h2><p>Declared providers and their execution profiles.</p></div>
          <span class="badge">providers.list</span>
        </div>
        <div class="card-body"><dl class="facts" id="providers"></dl></div>
      </section>
      <section class="card">
        <div class="card-head">
          <div><h2>Models</h2><p>Model catalog entries by provider.</p></div>
          <span class="badge">models.list</span>
        </div>
        <div class="card-body"><dl class="facts" id="models"></dl></div>
      </section>
    </div>
    <p class="note">Default bind 127.0.0.1 &mdash; no authentication. Read routes are
      read-only by construction; verify routes answer 403 RESERVED_OPERATION.</p>
    </section>

    <section id="view-servers" class="view" hidden>
      <p class="eyebrow">Local Inference</p>
      <h1>Inference servers</h1>
      <p class="lede">Registry, detection, and advisory tier recommendations from
        <code>tlkdoc serve ...</code> &mdash; the same operations as the CLI; every value
        below is the live API response, nothing is mocked.</p>
      <div class="grid">
        <section class="card">
          <div class="card-head">
            <div><h2>Registry</h2><p>Declared servers, Docker image, detection, native vector.</p></div>
            <span class="badge">serve.list</span>
          </div>
          <div class="card-body"><dl class="facts" id="s-registry"></dl></div>
        </section>
        <section class="card">
          <div class="card-head">
            <div><h2>Recommendations</h2><p>Advisory tier verdicts &mdash; never selects providers or execution paths.</p></div>
            <span class="badge">serve.recommend</span>
          </div>
          <div class="card-body"><dl class="facts" id="s-reco"></dl></div>
        </section>
        <section class="card card--plan">
          <div class="card-head">
            <div><h2>Plan &amp; install</h2>
              <p>plan &rarr; install with confirmation &mdash; identifiers only, code-owned vector.</p></div>
            <span class="badge">serve.plan / serve.execute</span>
          </div>
          <form class="install-form" id="s-form">
            <label class="field">Server
              <select id="s-server"></select>
            </label>
            <label class="field">Via
              <select id="s-via">
                <option value="auto">auto</option>
                <option value="native">native</option>
                <option value="docker">docker</option>
              </select>
            </label>
            <label class="field">GPU
              <select id="s-gpu">
                <option value="auto">auto</option>
                <option value="on">on</option>
                <option value="off">off (CPU)</option>
              </select>
            </label>
            <label class="field" id="s-variant-field" hidden>Variant
              <select id="s-variant">
                <option value="desktop">desktop (GUI)</option>
                <option value="headless">headless (API)</option>
              </select>
            </label>
            <label class="field">Model id (required for vllm)
              <input id="s-model" spellcheck="false" autocomplete="off">
            </label>
          </form>
          <div class="install-actions">
            <button class="btn btn--secondary" id="s-plan" type="button">Plan</button>
            <button class="btn" id="s-run" type="button">Install</button>
          </div>
          <ol class="stage-list" id="s-stages" hidden>
            <li data-stage="plan"><span class="stage-dot"></span>
              <span class="stage-name">Plan vector</span><span class="stage-state">pending</span></li>
            <li data-stage="install"><span class="stage-dot"></span>
              <span class="stage-name">Install server</span><span class="stage-state">pending</span></li>
          </ol>
          <div class="progress" id="s-progress"><div class="progress-bar"></div></div>
          <pre class="result" id="s-result"></pre>
        </section>
      </div>
      <p class="note">Recommendations are advisory only (runtime/tiers.toml); provider
        selection keeps flowing ProcessingProfile &rarr; ExecutionPolicy &rarr;
        ExecutionPlan. Execution is confirm-gated (equivalent of --yes); fail-closed
        error codes appear verbatim.</p>
    </section>

    <section id="view-install" class="view" hidden>
      <p class="eyebrow">Provider Install</p>
      <h1>Install provider</h1>
      <p class="lede">Plan, install a provider runtime, then download a model.
        Steps run in order with live progress; each execution step requires
        explicit confirmation &mdash; identifiers only, the server resolves the
        trusted command.</p>
      <div class="grid">
        <section class="card card--plan">
          <div class="card-head">
            <div><h2>Install &amp; download</h2>
              <p>plan &rarr; runtime install &rarr; model download</p></div>
            <span class="badge">tlkdoc install</span>
          </div>
          <form class="install-form" id="install-form">
            <label class="field">Provider
              <select id="i-provider"></select>
            </label>
            <label class="field">Profile
              <select id="i-profile">
                <option value="cpu">cpu</option>
                <option value="nvidia">nvidia</option>
              </select>
            </label>
            <label class="field">Model
              <select id="i-model"></select>
            </label>
          </form>
          <div class="install-actions">
            <button class="btn btn--secondary" id="i-plan" type="button">Plan</button>
            <button class="btn" id="i-run" type="button">Install</button>
          </div>
          <ol class="stage-list" id="i-stages" hidden>
            <li data-stage="plan"><span class="stage-dot"></span>
              <span class="stage-name">Plan runtime</span><span class="stage-state">pending</span></li>
            <li data-stage="install"><span class="stage-dot"></span>
              <span class="stage-name">Install runtime</span><span class="stage-state">pending</span></li>
            <li data-stage="model"><span class="stage-dot"></span>
              <span class="stage-name">Download model</span><span class="stage-state">pending</span></li>
          </ol>
          <div class="progress" id="i-progress"><div class="progress-bar"></div></div>
          <pre class="result" id="i-result"></pre>
        </section>
      </div>
      <p class="note">Model download requires the runtime to be READY; every failure
        fails closed with a machine-readable code recorded in install-state.json.</p>
    </section>
  </div>
</main>
<script>
const enc = encodeURIComponent;
const render = (id, pairs) => {
  const dl = document.getElementById(id);
  dl.replaceChildren();
  if (!pairs.length) {
    const row = document.createElement("div");
    const note = document.createElement("dt");
    note.className = "is-empty";
    note.textContent = "no data";
    row.appendChild(note);
    dl.appendChild(row);
    return;
  }
  for (const [label, value] of pairs) {
    const row = document.createElement("div");
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value === null || value === undefined ? "\u2014"
      : (typeof value === "object" ? JSON.stringify(value) : String(value));
    row.append(dt, dd);
    dl.appendChild(row);
  }
};
const rowsFromObject = (obj) => Object.entries(obj).map(
  ([key, value]) => [key.replace(/_/g, " "), value]
);
const post = async (path, payload) => {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload),
    });
    return await response.json();
  } catch (err) {
    return { ok: false, error: { code: "NETWORK_ERROR" } };
  }
};
const showJson = (id, body) => {
  document.getElementById(id).textContent = JSON.stringify(
    body.ok ? body.result : { ok: false, error: body.error }, null, 2
  );
};

// --- section navigation -------------------------------------------------------
document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(
      (item) => item.classList.toggle("is-active", item === button)
    );
    document.querySelectorAll(".view").forEach((view) => {
      view.hidden = view.id !== "view-" + button.dataset.view;
    });
    document.title = button.textContent + " · EDI Runtime Control Panel";
  });
});

// --- catalog ------------------------------------------------------------------
const catalog = { providers: [], models: [] };
const fillOptions = (select, entries, getValue, getText) => {
  select.replaceChildren();
  for (const entry of entries) {
    const option = document.createElement("option");
    option.value = getValue(entry);
    option.textContent = getText(entry);
    select.appendChild(option);
  }
};
function fillModelOptions() {
  const provider = document.getElementById("i-provider").value;
  const select = document.getElementById("i-model");
  select.replaceChildren();
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "None (runtime only)";
  select.appendChild(none);
  for (const model of catalog.models) {
    if (model.provider_id !== provider) continue;
    const option = document.createElement("option");
    option.value = model.model_id;
    option.textContent = model.model_id;
    select.appendChild(option);
  }
}
function fillInstallSelects() {
  fillOptions(
    document.getElementById("i-provider"),
    catalog.providers,
    (entry) => entry.provider_id,
    (entry) => entry.provider_id
  );
  fillModelOptions();
}
document.getElementById("i-provider").addEventListener("change", fillModelOptions);

async function loadServers() {
  const registry = await fetch("/admin/runtime/servers").then(r => r.json());
  if (registry.ok) {
    const rows = registry.result.servers;
    render("s-registry", rows.map((entry) => [
      entry.display_name,
      "port " + entry.default_port + " · " + entry.image +
        (entry.community_image ? " (community)" : "") + " · " +
        entry.detection.status +
        (entry.detection.version ? " " + entry.detection.version : "") +
        " · native " + entry.native_vector,
    ]));
    fillOptions(
      document.getElementById("s-server"),
      rows,
      (entry) => entry.server_id,
      (entry) => entry.display_name
    );
    if (typeof syncVariantField === "function") syncVariantField();
  } else {
    render("s-registry", [["error", registry.error.code]]);
  }
  const reco = await fetch("/admin/runtime/servers/recommendations").then(r => r.json());
  if (reco.ok) {
    const data = reco.result;
    const rows = [[
      "tier",
      data.tier + (data.vram_mib === null || data.vram_mib === undefined
        ? "" : " · " + data.vram_mib + " MiB"),
    ]];
    for (const entry of data.recommendations) {
      rows.push([entry.display_name, entry.verdict + " · " + entry.reasons.join(", ")]);
    }
    render("s-reco", rows);
  } else {
    render("s-reco", [["error", reco.error.code]]);
  }
}

async function load() {
  const host = await fetch("/admin/runtime/host").then(r => r.json());
  if (host.ok) {
    render("host", rowsFromObject(host.result));
  } else {
    render("host", [["error", host.error.code]]);
  }
  const status = await fetch("/admin/runtime/status").then(r => r.json());
  if (status.ok) {
    const data = status.result;
    render("status", [
      ["tier", data.tier + (data.vram_mib === null || data.vram_mib === undefined
        ? "" : " · " + data.vram_mib + " MiB")],
      ["providers", data.providers.map(
        (entry) => entry.provider_id + "/" + entry.profile + ": " + entry.status
      ).join(", ") || "\u2014"],
      ["models", data.models.map(
        (entry) => entry.model_id + ": " + entry.status
      ).join(", ") || "\u2014"],
      ["servers", data.servers.map(
        (entry) => entry.display_name + ": " + entry.status
      ).join(", ") || "\u2014"],
    ]);
  } else {
    render("status", [["error", status.error.code]]);
  }
  const providers = await fetch("/admin/runtime/providers").then(r => r.json());
  if (providers.ok) {
    catalog.providers = providers.result.providers;
    render("providers", catalog.providers.map(
      (entry) => [entry.provider_id, entry.profiles.join(", ")]
    ));
    fillInstallSelects();
  } else {
    render("providers", [["error", providers.error.code]]);
  }
  const models = await fetch("/admin/runtime/models").then(r => r.json());
  if (models.ok) {
    catalog.models = models.result.models;
    render("models", catalog.models.map(
      (entry) => [entry.model_id, entry.provider_id]
    ));
    fillModelOptions();
  } else {
    render("models", [["error", models.error.code]]);
  }
  loadServers();
}

// --- staged flows with progress animation --------------------------------------
const setStage = (list, name, state) => {
  const item = list.querySelector('[data-stage="' + name + '"]');
  item.className = state ? "is-" + state : "";
  item.querySelector(".stage-state").textContent = state === "active" ? "running" : state;
};
const resetStages = (list) => {
  list.hidden = false;
  for (const item of list.querySelectorAll("li")) {
    item.className = "";
    item.querySelector(".stage-state").textContent = "pending";
  }
};
const progressOn = (element, isDownload) => {
  element.classList.toggle("is-download", Boolean(isDownload));
  element.classList.add("is-active");
};
const progressOff = (element) => element.classList.remove("is-active");

// --- install page: provider plan -> install -> model download ------------------
const stageList = document.getElementById("i-stages");
const progress = document.getElementById("i-progress");

document.getElementById("i-plan").addEventListener("click", async () => {
  const body = await post(
    "/admin/runtime/providers/" + enc(document.getElementById("i-provider").value) +
      "/install-plans",
    { profile: document.getElementById("i-profile").value }
  );
  showJson("i-result", body);
});

document.getElementById("i-run").addEventListener("click", async () => {
  const provider = document.getElementById("i-provider").value;
  const profile = document.getElementById("i-profile").value;
  const model = document.getElementById("i-model").value;
  const runButton = document.getElementById("i-run");
  const planButton = document.getElementById("i-plan");
  runButton.disabled = true;
  planButton.disabled = true;
  resetStages(stageList);
  document.getElementById("i-result").textContent = "";
  const collected = {};
  try {
    setStage(stageList, "plan", "active");
    progressOn(progress, false);
    const plan = await post(
      "/admin/runtime/providers/" + enc(provider) + "/install-plans",
      { profile: profile }
    );
    progressOff(progress);
    if (!plan.ok) {
      setStage(stageList, "plan", "failed");
      setStage(stageList, "install", "skipped");
      setStage(stageList, "model", "skipped");
      showJson("i-result", plan);
      return;
    }
    collected.plan = plan.result;
    setStage(stageList, "plan", "done");

    setStage(stageList, "install", "active");
    progressOn(progress, false);
    const install = await post(
      "/admin/runtime/providers/" + enc(provider) + "/install",
      { profile: profile, confirm: true }
    );
    progressOff(progress);
    if (!install.ok) {
      setStage(stageList, "install", "failed");
      if (model) setStage(stageList, "model", "skipped");
      showJson("i-result", install);
      return;
    }
    collected.install = install.result;
    setStage(stageList, "install", "done");

    if (!model) {
      setStage(stageList, "model", "skipped");
    } else {
      setStage(stageList, "model", "active");
      progressOn(progress, true);
      const pull = await post(
        "/admin/runtime/models/" + enc(model) + "/pull",
        { profile: profile, confirm: true }
      );
      progressOff(progress);
      if (!pull.ok) {
        setStage(stageList, "model", "failed");
        showJson("i-result", pull);
        return;
      }
      collected.model = pull.result;
      setStage(stageList, "model", "done");
    }
    document.getElementById("i-result").textContent = JSON.stringify(collected, null, 2);
  } finally {
    runButton.disabled = false;
    planButton.disabled = false;
  }
});

// --- servers page: plan -> install --------------------------------------------
const serverStageList = document.getElementById("s-stages");
const serverProgress = document.getElementById("s-progress");
const syncVariantField = () => {
  const isLmstudio = document.getElementById("s-server").value === "lmstudio";
  const via = document.getElementById("s-via").value;
  document.getElementById("s-variant-field").hidden = !(isLmstudio && via !== "native");
};
document.getElementById("s-server").addEventListener("change", syncVariantField);
document.getElementById("s-via").addEventListener("change", syncVariantField);
const serveRequest = () => {
  const payload = {
    via: document.getElementById("s-via").value,
    gpu: document.getElementById("s-gpu").value,
  };
  const model = document.getElementById("s-model").value;
  if (model) payload.model = model;
  if (!document.getElementById("s-variant-field").hidden) {
    payload.variant = document.getElementById("s-variant").value;
  }
  return payload;
};
const servePath = (action) =>
  "/admin/runtime/servers/" + enc(document.getElementById("s-server").value) + "/" + action;

document.getElementById("s-plan").addEventListener("click", async () => {
  const body = await post(servePath("install-plans"), serveRequest());
  showJson("s-result", body);
});

document.getElementById("s-run").addEventListener("click", async () => {
  const request = serveRequest();
  const runButton = document.getElementById("s-run");
  const planButton = document.getElementById("s-plan");
  runButton.disabled = true;
  planButton.disabled = true;
  resetStages(serverStageList);
  document.getElementById("s-result").textContent = "";
  try {
    setStage(serverStageList, "plan", "active");
    progressOn(serverProgress, false);
    const plan = await post(servePath("install-plans"), request);
    progressOff(serverProgress);
    if (!plan.ok) {
      setStage(serverStageList, "plan", "failed");
      setStage(serverStageList, "install", "skipped");
      showJson("s-result", plan);
      return;
    }
    setStage(serverStageList, "plan", "done");

    setStage(serverStageList, "install", "active");
    progressOn(serverProgress, false);
    const install = await post(
      servePath("install"),
      Object.assign({}, request, { confirm: true })
    );
    progressOff(serverProgress);
    if (!install.ok) {
      setStage(serverStageList, "install", "failed");
      showJson("s-result", install);
      return;
    }
    setStage(serverStageList, "install", "done");
    document.getElementById("s-result").textContent = JSON.stringify(
      { plan: plan.result, install: install.result }, null, 2
    );
  } finally {
    runButton.disabled = false;
    planButton.disabled = false;
  }
});

load();
</script>
</body>
</html>
"""
