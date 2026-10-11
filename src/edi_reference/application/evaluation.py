"""Offline evaluation of classification and field extraction against a labelled manifest.

Framework-free and deterministic. The manifest, the predictions and the report
are the caller's files; for private documents they live outside the repository
(for example under `.edi/eval/`, which is ignored).

Ground truth is never taken from file names alone. `init_manifest` turns a
naming convention into *draft* labels; only entries marked ``verified`` are
scored unless the caller explicitly includes drafts.

Field values are compared in canonical form: money as a decimal amount, dates
as ISO-8601, tax ids as digits, other text case- and spacing-insensitively.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from edi_reference.domain.classification import UNKNOWN_DOCUMENT_TYPE

MANIFEST_SCHEMA = "tlkdoc.eval-manifest/v1"
REPORT_SCHEMA = "tlkdoc.eval-report/v1"
STATUSES = ("verified", "draft", "needs_review", "todo")
DEFAULT_NAME_PATTERN = r"^(?P<package>[^_]+)_(?P<label>.+)$"

# Generic Indonesian document terms → proposed category. A category outside the active
# taxonomy is scored as UNKNOWN (the system must abstain), but the proposal is kept.
# "draft" still needs a person to confirm it; "needs_review" is known to be ambiguous.
DEFAULT_LABEL_MAP: dict[str, tuple[str | None, str]] = {
    "invoice": ("INVOICE", "draft"),
    "kuitansi": ("RECEIPT", "draft"),
    "spp": ("PAYMENT_REQUEST", "draft"),
    "po": ("PURCHASE_ORDER", "draft"),
    "kontrak": ("CONTRACT", "draft"),
    "pesanan": ("ORDER_LETTER", "draft"),
    "npwp": ("TAX_REGISTRATION_CERTIFICATE", "draft"),
    "spk": ("WORK_ORDER", "draft"),
    "adendum": ("CONTRACT_AMENDMENT", "draft"),
    "nota_dinas": ("INTERNAL_MEMORANDUM", "draft"),
    "faktur": ("TAX_INVOICE", "needs_review"),  # may be a commercial invoice
    "bast": ("HANDOVER_REPORT", "needs_review"),  # samples showed inspection content
    "bapp": (None, "needs_review"),  # payment, inspection or service usage report
}
FIELD_TYPES = ("PAYMENT_REQUEST", "INVOICE", "TAX_INVOICE", "RECEIPT")


def split_for(package: str, holdout_share: float = 0.4) -> str:
    """Stable package-level split, so documents of one package never straddle dev and holdout."""
    bucket = int(hashlib.sha256(package.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "holdout" if bucket < holdout_share else "dev"


def init_manifest(files: Iterable[tuple[Path, str]], *, name_pattern: str = DEFAULT_NAME_PATTERN,
                  label_map: dict[str, tuple[str | None, str]] | None = None,
                  field_packages: int = 0, schema_fields: dict[str, list[str]] | None = None) -> dict:
    """Draft manifest from `(path, group)` pairs. Field slots are created for `field_packages`
    holdout packages that contain every type in FIELD_TYPES, using `schema_fields[type]`."""
    pattern = re.compile(name_pattern)
    mapping = DEFAULT_LABEL_MAP if label_map is None else label_map
    documents: list[dict] = []
    for path, group in sorted(files, key=lambda item: str(item[0])):
        match = pattern.match(path.stem)
        package = match.group("package") if match else path.stem
        label = (match.group("label") if match else path.stem).lower()
        expected, status = mapping.get(label, (None, "needs_review"))
        documents.append({"doc_key": f"{group}/{path.stem}", "path": str(path), "group": group, "package": package,
                          "label": label, "split": split_for(package), "expected_type": expected,
                          "type_status": status, "fields": {}})
    if field_packages and schema_fields:
        by_package: dict[str, dict[str, dict]] = {}
        for doc in documents:
            if doc["split"] == "holdout" and doc["expected_type"] in FIELD_TYPES:
                by_package.setdefault(doc["package"], {})[doc["expected_type"]] = doc
        complete = sorted(p for p, docs in by_package.items() if set(docs) >= set(FIELD_TYPES))
        for package in complete[:field_packages]:
            for doc_type, doc in by_package[package].items():
                doc["fields"] = {name: {"value": None, "status": "todo"} for name in schema_fields.get(doc_type, [])}
    return {"schema": MANIFEST_SCHEMA, "name_pattern": name_pattern, "documents": documents}


def validate_manifest(manifest: dict) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("MANIFEST_SCHEMA_UNSUPPORTED")
    keys = Counter(doc["doc_key"] for doc in manifest["documents"])
    if any(n > 1 for n in keys.values()):
        raise ValueError("DUPLICATE_DOC_KEY")
    for doc in manifest["documents"]:
        if doc["type_status"] not in STATUSES:
            raise ValueError(f"INVALID_TYPE_STATUS:{doc['doc_key']}")
        for name, slot in doc.get("fields", {}).items():
            if slot.get("status") not in STATUSES:
                raise ValueError(f"INVALID_FIELD_STATUS:{doc['doc_key']}:{name}")


# ---------------------------------------------------------------- review sheet
REVIEW_COLUMNS = ("doc_key", "kind", "name", "value", "status", "note", "verified")


def review_rows(manifest: dict) -> list[dict[str, str]]:
    """One row per document type and per field slot; people set `verified` to y after checking."""
    rows = []
    for doc in manifest["documents"]:
        rows.append({"doc_key": doc["doc_key"], "kind": "type", "name": "expected_type",
                     "value": doc["expected_type"] or "", "status": doc["type_status"], "note": doc.get("type_note", ""),
                     "verified": "y" if doc["type_status"] == "verified" else ""})
        for name, slot in doc.get("fields", {}).items():
            rows.append({"doc_key": doc["doc_key"], "kind": "field", "name": name,
                         "value": "" if slot.get("value") is None else str(slot["value"]), "status": slot["status"],
                         "note": slot.get("note", ""), "verified": "y" if slot["status"] == "verified" else ""})
    return rows


def apply_review(manifest: dict, rows: Iterable[dict[str, str]]) -> int:
    """Write reviewed rows back. A row marked verified stores its value (empty = absent) as verified.
    Unmarked rows only update a draft's value. Returns the number of slots changed."""
    docs = {doc["doc_key"]: doc for doc in manifest["documents"]}
    changed = 0
    for row in rows:
        doc = docs.get(row["doc_key"])
        if doc is None:
            raise ValueError(f"UNKNOWN_DOC_KEY:{row['doc_key']}")
        verified = row.get("verified", "").strip().lower() in ("y", "yes", "ya", "1", "true")
        value = row.get("value", "").strip() or None
        if row["kind"] == "type":
            new = (value, "verified" if verified else doc["type_status"])
            if (doc["expected_type"], doc["type_status"]) != new:
                doc["expected_type"], doc["type_status"] = new
                changed += 1
            if row.get("note"):
                doc["type_note"] = row["note"]
            continue
        slot = doc["fields"].get(row["name"])
        if slot is None:
            raise ValueError(f"UNKNOWN_FIELD:{row['doc_key']}:{row['name']}")
        status = "verified" if verified else ("draft" if value is not None else slot["status"])
        if (slot.get("value"), slot["status"]) != (value, status):
            slot.update(value=value, status=status)
            changed += 1
        if row.get("note"):
            slot["note"] = row["note"]
    validate_manifest(manifest)
    return changed


# ---------------------------------------------------------------- canonical values
def loose_text(value: str) -> str:
    """Case-, punctuation- and spacing-insensitive form for names and free text."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", value.casefold()).split())


Canonicalizer = Callable[[str, str], str | None]


def canonical(value_type: str, raw: str | None, normalize: Canonicalizer) -> str | None:
    """`normalize(value_type, raw)` returns a canonical string for typed values or None."""
    if raw is None:
        return None
    if value_type in ("money", "number"):
        return _decimal(normalize(value_type, raw))
    if value_type in ("date", "tax_id"):
        return normalize(value_type, raw)
    return loose_text(raw) or None


def _decimal(value: str | None) -> str | None:
    """Numbers compare by value: a printed `58.739.868` equals an expected `58739868.00`."""
    if value is None:
        return None
    try:
        return format(Decimal(value).normalize(), "f")
    except InvalidOperation:
        return value


def expected_canonical(value_type: str, value: str | None) -> str | None:
    if value is None:
        return None
    if value_type == "tax_id":
        return re.sub(r"\D", "", value)
    if value_type in ("money", "number"):
        return _decimal(value.strip())
    if value_type == "date":
        return value.strip()
    return loose_text(value)


# ---------------------------------------------------------------- scoring
@dataclass(frozen=True, slots=True)
class ScoreOptions:
    include_draft: bool = False
    taxonomy: frozenset[str] = frozenset()
    split: str | None = None  # "dev", "holdout" or None for all


def _countable(status: str, options: ScoreOptions) -> bool:
    return status == "verified" or (options.include_draft and status == "draft")


def effective_type(expected: str, taxonomy: frozenset[str]) -> str:
    return expected if expected in taxonomy or expected == UNKNOWN_DOCUMENT_TYPE else UNKNOWN_DOCUMENT_TYPE


def score(manifest: dict, predictions: dict[str, dict], *, value_types: dict[str, str],
          normalize: Canonicalizer, options: ScoreOptions) -> dict:
    """Classification and field metrics. `predictions` maps doc_key → prediction record."""
    validate_manifest(manifest)
    docs = [d for d in manifest["documents"] if options.split is None or d["split"] == options.split]
    return {"schema": REPORT_SCHEMA,
            "options": {"include_draft": options.include_draft, "split": options.split or "all",
                        "taxonomy": sorted(options.taxonomy)},
            "coverage": _coverage(docs, predictions),
            "classification": _classification(docs, predictions, options),
            "fields": _fields(docs, predictions, value_types, normalize, options)}


def _coverage(docs: list[dict], predictions: dict[str, dict]) -> dict:
    return {"documents": len(docs), "predicted": sum(d["doc_key"] in predictions for d in docs),
            "type_status": dict(Counter(d["type_status"] for d in docs)),
            "field_status": dict(Counter(s["status"] for d in docs for s in d.get("fields", {}).values()))}


def _classification(docs: list[dict], predictions: dict[str, dict], options: ScoreOptions) -> dict:
    rows = []
    for doc in docs:
        if doc["expected_type"] is None or not _countable(doc["type_status"], options):
            continue
        prediction = predictions.get(doc["doc_key"])
        if prediction is None:
            continue
        expected = effective_type(doc["expected_type"], options.taxonomy)
        predicted = prediction.get("document_type") or UNKNOWN_DOCUMENT_TYPE
        rows.append((expected, predicted, prediction.get("status") != "COMPLETED"))
    labels = sorted({e for e, _, _ in rows} | {p for _, p, _ in rows})
    per_class = {}
    for label in labels:
        tp = sum(e == label and p == label for e, p, _ in rows)
        fp = sum(e != label and p == label for e, p, _ in rows)
        fn = sum(e == label and p != label for e, p, _ in rows)
        per_class[label] = {"support": tp + fn, "tp": tp, "fp": fp, "fn": fn,
                            "precision": _ratio(tp, tp + fp), "recall": _ratio(tp, tp + fn)}
    confusion = Counter((e, p) for e, p, _ in rows if e != p)
    return {
        "scored": len(rows), "correct": sum(e == p for e, p, _ in rows),
        "accuracy": _ratio(sum(e == p for e, p, _ in rows), len(rows)),
        # The costly error: a confident wrong category rather than an abstention.
        "wrong_not_unknown": sum(e != p and p != UNKNOWN_DOCUMENT_TYPE for e, p, _ in rows),
        "abstained_wrongly": sum(e != UNKNOWN_DOCUMENT_TYPE and p == UNKNOWN_DOCUMENT_TYPE for e, p, _ in rows),
        "processing_failures": sum(failed for _, _, failed in rows),
        "per_class": per_class,
        "confusion": [{"expected": e, "predicted": p, "count": n} for (e, p), n in sorted(confusion.items())],
    }


def _fields(docs: list[dict], predictions: dict[str, dict], value_types: dict[str, str],
            normalize: Canonicalizer, options: ScoreOptions) -> dict:
    stats: dict[str, Counter] = {}
    mismatches = []
    for doc in docs:
        prediction = predictions.get(doc["doc_key"])
        if prediction is None:
            continue
        predicted = {f["field_name"]: f for f in prediction.get("fields", [])}
        for name, slot in doc.get("fields", {}).items():
            if not _countable(slot["status"], options):
                continue
            value_type = value_types.get(name, "string")
            want = expected_canonical(value_type, slot.get("value"))
            got_field = predicted.get(name)
            present = got_field is not None and got_field.get("state") == "PRESENT"
            got = canonical(value_type, got_field.get("raw_value"), normalize) if got_field and present else None
            counter = stats.setdefault(name, Counter())
            if want is None:
                outcome = "false_present" if present else "correct_absent"
            elif not present:
                outcome = "missed"
            elif got == want:
                outcome = "correct"
            else:
                outcome = "wrong"
            counter[outcome] += 1
            if outcome in ("wrong", "false_present", "missed"):
                mismatches.append({"doc_key": doc["doc_key"], "field": name, "outcome": outcome})
    per_field = {name: _field_metrics(counter) for name, counter in sorted(stats.items())}
    total: Counter = Counter()
    for counter in stats.values():
        total.update(counter)
    return {"total": _field_metrics(total), "per_field": per_field, "mismatches": mismatches}


def _field_metrics(counter: Counter) -> dict:
    correct, wrong, missed, false_present = (counter[k] for k in ("correct", "wrong", "missed", "false_present"))
    return {"correct": correct, "wrong": wrong, "missed": missed, "false_present": false_present,
            "correct_absent": counter["correct_absent"],
            # precision: of the values the system asserted, how many were right
            "precision": _ratio(correct, correct + wrong + false_present),
            # recall: of the values the document holds, how many the system found correctly
            "recall": _ratio(correct, correct + wrong + missed)}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def format_report(report: dict) -> str:
    c, f = report["classification"], report["fields"]["total"]
    lines = [f"documents: {report['coverage']['documents']}, predicted: {report['coverage']['predicted']}, "
             f"split: {report['options']['split']}, drafts included: {report['options']['include_draft']}",
             f"classification: {c['correct']}/{c['scored']} correct (accuracy {c['accuracy']}), "
             f"wrong-not-UNKNOWN {c['wrong_not_unknown']}, abstained wrongly {c['abstained_wrongly']}, "
             f"processing failures {c['processing_failures']}"]
    for label, m in c["per_class"].items():
        lines.append(f"  {label:<32} support {m['support']:>3}  precision {m['precision']}  recall {m['recall']}")
    lines.append(f"fields: correct {f['correct']}, wrong {f['wrong']}, missed {f['missed']}, "
                 f"false present {f['false_present']} (precision {f['precision']}, recall {f['recall']})")
    for name, m in report["fields"]["per_field"].items():
        lines.append(f"  {name:<28} correct {m['correct']:>3} wrong {m['wrong']:>3} missed {m['missed']:>3} "
                     f"false+ {m['false_present']:>3}  precision {m['precision']}  recall {m['recall']}")
    return "\n".join(lines)
