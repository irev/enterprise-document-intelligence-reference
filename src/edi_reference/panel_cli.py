"""`tlkdoc serve-panel` and `tlkdoc panel-user` commands (RI-4.11)."""

from __future__ import annotations

import argparse
import getpass
import os
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
    serve.add_argument("--lms", type=Path, default=Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms"))
    serve.add_argument("--llm-port", type=int, default=12340)
    serve.add_argument("--api-key-env", default="LM_STUDIO_API_KEY",
                       help="environment variable holding the local model server API key (empty to disable)")
    serve.add_argument("--env-file", type=Path, help="dotenv file to read --api-key-env from; the value is never printed")

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
    import logging

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
    )
    try:
        server, _ = create_server(settings)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    scheme = "https" if args.tls_cert else "http"
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    print(f"tlkdoc control panel on {scheme}://{shown}:{args.port}/  (Ctrl+C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ncontrol panel stopped")
    finally:
        server.server_close()
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
