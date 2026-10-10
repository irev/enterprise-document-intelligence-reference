"""`tlkdoc serve-panel` and `tlkdoc panel-user` commands (RI-4.11)."""

from __future__ import annotations

import argparse
import getpass
import os
import re
import sys
from pathlib import Path

from edi_reference.application.panel_auth import Role, UserStore
from edi_reference.application.runtime_installer import runtime_python

DEFAULT_STATE = Path(".edi/panel")
LEGACY_MODELS = Path(".edi/models/paddle-ocr/legacy-en")


def add_parsers(commands, *, runtime_root: Path) -> None:
    serve = commands.add_parser("serve-panel", help="control panel: runtime, documents, benchmark, configuration (login required)")
    serve.add_argument("--bind", dest="host", default="127.0.0.1",
                       help="bind address; anything but loopback requires --tls-cert/--tls-key")
    serve.add_argument("--port", type=int, default=8443)
    serve.add_argument("--tls-cert", type=Path)
    serve.add_argument("--tls-key", type=Path)
    serve.add_argument("--allowed-host", action="append", default=[],
                       help="extra Host header value clients use, e.g. panel.lan:8443 (repeatable)")
    serve.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    serve.add_argument("--ocr-python", type=Path, default=runtime_python(runtime_root / "paddle-ocr" / "cpu"))
    serve.add_argument("--ocr-det-name", default="PP-OCRv3_mobile_det")
    serve.add_argument("--ocr-det-dir", type=Path, default=LEGACY_MODELS / "en_PP-OCRv3_det_infer")
    serve.add_argument("--ocr-rec-name", default="en_PP-OCRv4_mobile_rec")
    serve.add_argument("--ocr-rec-dir", type=Path, default=LEGACY_MODELS / "en_PP-OCRv4_rec_infer")
    serve.add_argument("--title-rules", type=Path, default=Path("deploy/classification-profiles/title-rules-id-en.json"),
                       help="seed profile used only when no title-rule configuration exists yet")
    serve.add_argument("--extraction-registry", type=Path,
                       default=Path("deploy/classification-profiles/extraction-registry-business-documents.json"),
                       help="seed field catalog and per-category schemas, used only when none is configured yet")
    serve.add_argument("--lms", type=Path, default=Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms"))
    serve.add_argument("--llm-port", type=int, default=12340)
    serve.add_argument("--api-key-env", default="LM_STUDIO_API_KEY",
                       help="environment variable holding the local model server API key (empty to disable)")
    serve.add_argument("--env-file", type=Path, help="dotenv file to read --api-key-env from; the value is never printed")
    serve.add_argument("--api-port", type=int,
                       help="also serve the v1 data-plane API for applications on this port (same bind and TLS)")

    apps = commands.add_parser("app", help="manage applications that use the v1 data-plane API")
    apps.add_argument("action", choices=("add", "list", "key", "revoke", "disable", "enable", "profiles"))
    apps.add_argument("name", nargs="?", help="application id (add/key/disable/enable/profiles) or key id (revoke)")
    apps.add_argument("--tenant", help="tenant id for a new application")
    apps.add_argument("--display-name")
    apps.add_argument("--scopes", default="documents:write,documents:read,results:read")
    apps.add_argument("--rate-per-minute", type=int, default=60)
    apps.add_argument("--max-queued", type=int, default=100)
    apps.add_argument("--allowed", help="profiles: comma-separated processing profiles the application may use")
    apps.add_argument("--default", dest="default_profile", help="profiles: default processing profile (must be allowed)")
    apps.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)

    storage = commands.add_parser("storage", help="manage tenant storage connections for STORAGE_REFERENCE submissions")
    storage.add_argument("action", choices=("add", "list", "disable", "enable"))
    storage.add_argument("connection_id", nargs="?")
    storage.add_argument("--tenant", help="tenant that owns the storage")
    storage.add_argument("--broker-url", help="HTTPS URL of the tenant's grant broker")
    storage.add_argument("--origin", action="append", default=[],
                         help="https://host[:port] a grant may point to (repeatable)")
    storage.add_argument("--allow-private-network", action="store_true",
                         help="allow private/loopback addresses for this connection (never link-local or metadata)")
    storage.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)

    users = commands.add_parser("panel-user", help="manage control-panel users")
    users.add_argument("action", choices=("add", "passwd", "role", "disable", "enable", "list"))
    users.add_argument("username", nargs="?")
    users.add_argument("--role", choices=[r.name for r in Role])
    users.add_argument("--password-stdin", action="store_true", help="read the password from standard input")
    users.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)


def _password(args) -> str:
    if args.password_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("Kata sandi baru: ")
    if first != getpass.getpass("Ulangi kata sandi: "):
        raise ValueError("PASSWORDS_DO_NOT_MATCH")
    return first


def _load_env_file(path: Path, name: str) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name and not os.environ.get(name):
            os.environ[name] = value.strip().strip("'\"")


def run(args: argparse.Namespace) -> int:
    if args.command == "panel-user":
        return _users(args)
    if args.command == "app":
        return _apps(args)
    if args.command == "storage":
        return _storage(args)
    import logging
    import threading

    from edi_reference.adapters.control_panel_web import PanelSettings, create_server

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.env_file and args.api_key_env:
        _load_env_file(args.env_file, args.api_key_env)
    settings = PanelSettings(
        host=args.host, port=args.port, state_dir=args.state_dir.resolve(), ocr_python=args.ocr_python.absolute(),
        lms_cli=args.lms, llm_port=args.llm_port, api_key_env=args.api_key_env or None,
        default_profile=args.title_rules,
        default_ocr={"det_name": args.ocr_det_name, "det_dir": str(args.ocr_det_dir.resolve()),
                     "rec_name": args.ocr_rec_name, "rec_dir": str(args.ocr_rec_dir.resolve())},
        tls_cert=args.tls_cert, tls_key=args.tls_key, allowed_hosts=tuple(args.allowed_host),
        api_port=args.api_port, default_registry=args.extraction_registry,
    )
    try:
        server, panel = create_server(settings)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scheme = "https" if args.tls_cert else "http"
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"tlkdoc control panel on {scheme}://{shown}:{args.port}/  (Ctrl+C to stop)", flush=True)
    if panel.api_server is not None:
        threading.Thread(target=panel.api_server.serve_forever, name="api-listener", daemon=True).start()
        print(f"tlkdoc data-plane API v1 on {scheme}://{shown}:{args.api_port}/v1/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ncontrol panel stopped")
    finally:
        server.server_close()
        if panel.api_server is not None:
            panel.api.stop()
            panel.api_server.shutdown()
            panel.api_server.server_close()
    return 0


def _apps(args) -> int:
    from edi_reference.adapters.sqlite_api_store import SqliteApiStore
    from edi_reference.application.api_service import issue_key

    store = SqliteApiStore(args.state_dir / "api.sqlite3")
    try:
        if args.action == "list":
            for app in store.applications():
                active = [k["key_id"] for k in app["keys"] if not k["revoked_at"]]
                state = "disabled" if app["disabled"] else "active"
                print(f"{app['application_id']}\ttenant={app['tenant_id']}\t{state}\tkeys={','.join(active) or '-'}")
            return 0
        if not args.name:
            raise ValueError("NAME_REQUIRED")
        if args.action == "add":
            ident = re.compile(r"[a-z][a-z0-9-]{1,62}")
            if not args.tenant or not ident.fullmatch(args.tenant) or not ident.fullmatch(args.name):
                raise ValueError("APPLICATION_AND_TENANT_ID_REQUIRED (lowercase letters, digits, '-')")
            if store.application(args.name) is not None:
                raise ValueError("APPLICATION_EXISTS")
            store.create_application(application_id=args.name, tenant_id=args.tenant, name=args.display_name or args.name,
                                     default_profile="default", allowed_profiles=["default"],
                                     rate_per_minute=args.rate_per_minute, max_queued=args.max_queued,
                                     max_bytes=50 * 1024 * 1024, created_by="cli")
        elif args.action == "key":
            key_id, token = issue_key(store, args.name, [s.strip() for s in args.scopes.split(",") if s.strip()],
                                      created_by="cli")
            print(f"key_id: {key_id}")
            print(f"token:  {token}")
            print("Store this token now; it cannot be shown again.")
            return 0
        elif args.action == "revoke":
            store.revoke_key(args.name)
        elif args.action == "profiles":
            allowed = [p.strip() for p in (args.allowed or "").split(",") if p.strip()]
            if any(not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", p) for p in allowed):
                raise ValueError("INVALID_PROFILE_ID")
            store.set_application_profiles(args.name, allowed, args.default_profile or (allowed[0] if allowed else ""))
        else:
            store.set_application_disabled(args.name, args.action == "disable")
    except (ValueError, LookupError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    print(f"ok: {args.action} {args.name}")
    return 0


def _storage(args) -> int:
    from edi_reference.adapters.restricted_http import FileSecretStore
    from edi_reference.adapters.sqlite_api_store import SqliteApiStore
    from edi_reference.application.source_fetch import Origin, StorageConnection

    store = SqliteApiStore(args.state_dir / "api.sqlite3")
    try:
        if args.action == "list":
            for row in store.connections():
                state = "disabled" if row["disabled"] else "active"
                private = "\tprivate-network" if row["allow_private_network"] else ""
                print(f"{row['connection_id']}\ttenant={row['tenant_id']}\t{state}\tbroker={row['broker_url']}"
                      f"\torigins={','.join(row['origins'])}{private}")
            return 0
        if not args.connection_id:
            raise ValueError("CONNECTION_ID_REQUIRED")
        if args.action == "add":
            if not args.tenant or not re.fullmatch(r"[a-z][a-z0-9-]{1,62}", args.tenant):
                raise ValueError("TENANT_ID_REQUIRED (lowercase letters, digits, '-')")
            if not args.broker_url or not args.origin:
                raise ValueError("BROKER_URL_AND_ORIGIN_REQUIRED")
            if store.connection(args.connection_id) is not None:
                raise ValueError("STORAGE_CONNECTION_EXISTS")
            connection = StorageConnection(args.connection_id, args.tenant, args.broker_url,
                                           tuple(Origin.parse(o) for o in args.origin),
                                           allow_private_network=args.allow_private_network)
            secret = FileSecretStore(args.state_dir / "storage-secrets").create(connection.connection_id)
            store.create_connection(connection_id=connection.connection_id, tenant_id=connection.tenant_id,
                                    broker_url=connection.broker_url, origins=[str(o) for o in connection.origins],
                                    allow_private_network=connection.allow_private_network, created_by="cli")
            print(f"broker secret: {secret}")
            print("Configure this secret in the tenant's grant broker now; it cannot be shown again.")
            return 0
        store.set_connection_disabled(args.connection_id, args.action == "disable")
    except (ValueError, LookupError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        store.close()
    print(f"ok: {args.action} {args.connection_id}")
    return 0


def _users(args) -> int:
    store = UserStore(args.state_dir / "users.json")
    try:
        if args.action == "list":
            for user in store.all_users():
                print(f"{user.username}\t{user.role.name}\t{'disabled' if user.disabled else 'active'}")
            return 0
        if not args.username:
            raise ValueError("USERNAME_REQUIRED")
        if args.action == "add":
            if store.get(args.username) is not None:
                raise ValueError("USER_EXISTS")
            if not args.role:
                raise ValueError("ROLE_REQUIRED")
            store.upsert(args.username, _password(args), Role[args.role])
        elif args.action == "passwd":
            if store.get(args.username) is None:
                raise ValueError("USER_NOT_FOUND")
            store.upsert(args.username, _password(args))
        elif args.action == "role":
            if not args.role or store.get(args.username) is None:
                raise ValueError("ROLE_AND_EXISTING_USER_REQUIRED")
            store.upsert(args.username, None, Role[args.role])
        else:
            if store.get(args.username) is None:
                raise ValueError("USER_NOT_FOUND")
            store.upsert(args.username, None, disabled=args.action == "disable")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"ok: {args.action} {args.username}")
    return 0
