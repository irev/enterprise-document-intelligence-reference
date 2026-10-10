"""`tlkdoc eval init|run|score`: measure classification and field extraction on labelled documents.

Private sample documents, manifests, predictions and reports belong outside the
repository; the defaults are under `.edi/eval/`, which is git-ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from edi_reference.application.evaluation import (
    FIELD_TYPES,
    REVIEW_COLUMNS,
    ScoreOptions,
    apply_review,
    format_report,
    init_manifest,
    review_rows,
    score,
    validate_manifest,
)
from edi_reference.application.runtime_installer import runtime_python

EVAL_ROOT = Path(".edi/eval")
LEGACY_MODELS = Path(".edi/models/paddle-ocr/legacy-en")
SEED_RULES = Path("deploy/classification-profiles/title-rules-id-en.json")
SEED_REGISTRY = Path("deploy/classification-profiles/extraction-registry-business-documents.json")
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def add_parsers(commands, *, runtime_root: Path) -> None:
    ev = commands.add_parser("eval", help="evaluate classification and fields against a labelled manifest")
    sub = ev.add_subparsers(dest="eval_command", required=True)

    init = sub.add_parser("init", help="draft a manifest from a sample folder (labels need human verification)")
    init.add_argument("samples", type=Path, help="folder of documents; each sub-folder is a group")
    init.add_argument("--out", type=Path, default=EVAL_ROOT / "manifest.json")
    init.add_argument("--field-packages", type=int, default=10,
                      help="holdout packages that get field slots for SPP, invoice, tax invoice and receipt")
    init.add_argument("--extraction-registry", type=Path, default=SEED_REGISTRY)
    init.add_argument("--force", action="store_true", help="overwrite an existing manifest (loses verifications)")

    run = sub.add_parser("run", help="run the pipeline on manifest documents; resumable")
    run.add_argument("--manifest", type=Path, default=EVAL_ROOT / "manifest.json")
    run.add_argument("--out", type=Path, help="predictions JSONL (default .edi/eval/predictions-<mode>.jsonl)")
    run.add_argument("--mode", choices=("rules", "rules_then_llm", "llm"), default="rules")
    run.add_argument("--no-llm", action="store_true", help="classification only; no model calls, no field extraction")
    run.add_argument("--split", choices=("dev", "holdout"))
    run.add_argument("--fields-only", action="store_true", help="only documents that have field ground truth slots")
    run.add_argument("--limit", type=int)
    run.add_argument("--state-dir", type=Path, default=EVAL_ROOT / "state",
                     help="panel state whose active configuration is evaluated (seeded from deploy/ when new)")
    run.add_argument("--ocr-python", type=Path, default=runtime_python(runtime_root / "paddle-ocr" / "cpu"))
    run.add_argument("--ocr-det-name", default="PP-OCRv3_mobile_det")
    run.add_argument("--ocr-det-dir", type=Path, default=LEGACY_MODELS / "en_PP-OCRv3_det_infer")
    run.add_argument("--ocr-rec-name", default="en_PP-OCRv4_mobile_rec")
    run.add_argument("--ocr-rec-dir", type=Path, default=LEGACY_MODELS / "en_PP-OCRv4_rec_infer")
    run.add_argument("--lms", type=Path, default=Path.home() / ".lmstudio" / "bin" / ("lms.exe" if os.name == "nt" else "lms"))
    run.add_argument("--llm-port", type=int, default=12340)
    run.add_argument("--api-key-env", default="LM_STUDIO_API_KEY")
    run.add_argument("--env-file", type=Path, help="dotenv file to read --api-key-env from; the value is never printed")

    export = sub.add_parser("review-export", help="write a CSV review sheet (opens in a spreadsheet)")
    export.add_argument("--manifest", type=Path, default=EVAL_ROOT / "manifest.json")
    export.add_argument("--out", type=Path, default=EVAL_ROOT / "review.csv")
    export.add_argument("--fields-only", action="store_true", help="only field rows and their documents' type rows")

    imp = sub.add_parser("review-import", help="apply a reviewed CSV sheet to the manifest")
    imp.add_argument("sheet", type=Path)
    imp.add_argument("--manifest", type=Path, default=EVAL_ROOT / "manifest.json")

    sc = sub.add_parser("score", help="score predictions against verified labels")
    sc.add_argument("--manifest", type=Path, default=EVAL_ROOT / "manifest.json")
    sc.add_argument("--predictions", type=Path, required=True)
    sc.add_argument("--include-draft", action="store_true", help="also score draft labels (not a measurement)")
    sc.add_argument("--split", choices=("dev", "holdout"))
    sc.add_argument("--state-dir", type=Path, default=EVAL_ROOT / "state",
                    help="taxonomy and registry come from this state's active configuration when present")
    sc.add_argument("--report", type=Path, help="write the JSON report here")


def run(args: argparse.Namespace) -> int:
    try:
        return {"init": _init, "run": _run, "score": _score, "review-export": _review_export,
                "review-import": _review_import}[args.eval_command](args)
    except (ValueError, LookupError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _init(args) -> int:
    from edi_reference.application.extraction_registry import registry_from_dict

    if args.out.exists() and not args.force:
        raise ValueError("MANIFEST_EXISTS (use --force to overwrite; verified labels would be lost)")
    if not args.samples.is_dir():
        raise ValueError("SAMPLES_FOLDER_NOT_FOUND")
    files = []
    for path in sorted(args.samples.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUFFIXES:
            group = path.parent.relative_to(args.samples).as_posix() or "."
            files.append((path.resolve(), group))
    registry = registry_from_dict(_load(args.extraction_registry))
    schema_fields = {t: [f.field_name for f in registry.categories[t].fields] for t in FIELD_TYPES if t in registry.categories}
    manifest = init_manifest(files, field_packages=args.field_packages, schema_fields=schema_fields)
    _write_json(args.out, manifest)
    docs = manifest["documents"]
    print(f"manifest: {args.out} ({len(docs)} documents, {len({d['package'] for d in docs})} packages, "
          f"{sum(bool(d['fields']) for d in docs)} with field slots)")
    print("Labels are drafts from file names. Review them and set type_status / field status to \"verified\".")
    return 0


def _run(args) -> int:
    from edi_reference.adapters.control_panel_web import Panel, PanelSettings
    from edi_reference.panel_cli import _load_env_file

    manifest = _load(args.manifest)
    validate_manifest(manifest)
    out = args.out or EVAL_ROOT / f"predictions-{args.mode}{'-nollm' if args.no_llm else ''}.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(line)["doc_key"] for line in out.read_text(encoding="utf-8").splitlines() if line.strip()}
    docs = [d for d in manifest["documents"] if d["doc_key"] not in done
            and (args.split is None or d["split"] == args.split) and (not args.fields_only or d["fields"])]
    if args.limit is not None:
        docs = docs[:args.limit]
    if args.env_file and args.api_key_env:
        _load_env_file(args.env_file, args.api_key_env)
    panel = Panel(PanelSettings(
        host="127.0.0.1", port=0, state_dir=args.state_dir.resolve(), ocr_python=args.ocr_python.absolute(),
        lms_cli=args.lms, llm_port=args.llm_port, api_key_env=args.api_key_env or None, default_profile=SEED_RULES,
        default_ocr={"det_name": args.ocr_det_name, "det_dir": str(args.ocr_det_dir.resolve()),
                     "rec_name": args.ocr_rec_name, "rec_dir": str(args.ocr_rec_dir.resolve())},
        default_registry=SEED_REGISTRY))
    use_llm = not args.no_llm
    snap = panel.service.snapshot(mode_override=args.mode)
    if use_llm:
        panel.service.ensure_model(snap["pipeline"]["llm"]["model"], lambda message: print(message, flush=True))
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"{len(done)} already done, {len(docs)} to run -> {out}", flush=True)
    with out.open("a", encoding="utf-8") as stream:
        for index, doc in enumerate(docs, 1):
            meta = panel.store.put(Path(doc["path"]).read_bytes(), Path(doc["path"]).name, uploaded_by="eval")
            result = panel.service.process_document(meta["document_id"], snap, use_llm=use_llm)
            record = {"doc_key": doc["doc_key"], "sha256": meta["document_id"], "status": result.get("status"),
                      "error_code": result.get("error_code"), "document_type": result.get("document_type"),
                      "classification_source": result.get("classification_source"), "mode": args.mode,
                      "model": result.get("llm_model"), "config": result.get("config"),
                      "extraction_schema": result.get("extraction_schema"), "pages": result.get("pages_processed"),
                      "ocr_s": result.get("ocr_s"), "classify_s": result.get("classify_s"),
                      "extract_s": result.get("extract_s"),
                      "fields": [{k: f.get(k) for k in ("field_name", "value_type", "state", "raw_value")}
                                 for f in result.get("fields", [])]}
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            stream.flush()
            print(f"[{index}/{len(docs)}] {doc['doc_key']} -> {record['document_type']} ({record['status']})", flush=True)
    return 0


def _canonicalizer(registry):
    from edi_reference.adapters.normalizers import reference_normalizers
    from edi_reference.application.normalization import NormalizationRegistry
    from edi_reference.domain.normalization import NormalizationError

    normalizers = NormalizationRegistry(reference_normalizers())

    def normalize(value_type: str, raw: str) -> str | None:
        for normalizer_id, version in registry.normalizer_chain(value_type):
            try:
                value = normalizers.normalize(raw, normalizer_id=normalizer_id, version=version).value
            except NormalizationError:
                continue
            if isinstance(value, dict):
                return str(value.get("amount", value.get("value")))
            return str(value)
        return None

    return normalize


def _score(args) -> int:
    from edi_reference.application.extraction_registry import registry_from_dict
    from edi_reference.application.panel_config import ConfigStore

    manifest = _load(args.manifest)
    config = ConfigStore(args.state_dir / "config") if (args.state_dir / "config").is_dir() else None
    rules = config.active("title_rules") if config and config.active_version("title_rules") else _load(SEED_RULES)
    registry_content = (config.active("extraction_registry") if config and config.active_version("extraction_registry")
                        else _load(SEED_REGISTRY))
    registry = registry_from_dict(registry_content)
    predictions = {}
    for line in args.predictions.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            predictions[record["doc_key"]] = record
    report = score(manifest, predictions,
                   value_types={name: spec.value_type for name, spec in registry.fields.items()},
                   normalize=_canonicalizer(registry),
                   options=ScoreOptions(include_draft=args.include_draft, split=args.split,
                                        taxonomy=frozenset(rule["document_type"] for rule in rules["rules"])))
    print(format_report(report))
    if args.include_draft:
        print("NOTE: drafts included; this is not a measurement against verified ground truth.")
    if args.report:
        _write_json(args.report, report)
    return 0


def _review_export(args) -> int:
    import csv

    manifest = _load(args.manifest)
    validate_manifest(manifest)
    rows = review_rows(manifest)
    if args.fields_only:
        keep = {r["doc_key"] for r in rows if r["kind"] == "field"}
        rows = [r for r in rows if r["doc_key"] in keep]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig so spreadsheet programs detect the encoding
    with args.out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=REVIEW_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"review sheet: {args.out} ({len(rows)} rows). Set 'verified' to y for checked rows, then run review-import.")
    return 0


def _review_import(args) -> int:
    import csv

    manifest = _load(args.manifest)
    validate_manifest(manifest)
    with args.sheet.open(encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(4096)
        stream.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")  # spreadsheets in id-ID locales save with ';'
        changed = apply_review(manifest, csv.DictReader(stream, dialect=dialect))
    _write_json(args.manifest, manifest)
    print(f"updated {changed} entries in {args.manifest}")
    return 0
