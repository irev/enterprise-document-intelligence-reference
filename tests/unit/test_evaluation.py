"""Evaluation harness: draft manifests and scoring. Synthetic data only."""

import json
from pathlib import Path

import pytest

from edi_reference.application.evaluation import (
    ScoreOptions,
    format_report,
    init_manifest,
    loose_text,
    score,
    split_for,
    validate_manifest,
)

TAXONOMY = frozenset({"INVOICE", "RECEIPT", "PAYMENT_REQUEST", "TAX_INVOICE"})
TYPES = {"total_amount": "money", "document_date": "date", "tax_id": "tax_id", "issuer_name": "string",
         "document_number": "identifier"}


def fake_normalize(value_type, raw):
    digits = "".join(c for c in raw if c.isdigit())
    if value_type == "money":
        return f"{int(digits[:-2] or 0)}.{digits[-2:]}" if raw.endswith(",00") else None
    if value_type == "tax_id":
        return digits or None
    if value_type == "date":
        return "2026-07-15" if "Juli" in raw else None
    return None


def files(*names):
    return [(Path(f"/samples/{group}/{name}.pdf"), group) for group, name in (n.split("/") for n in names)]


def test_split_is_stable_and_per_package():
    assert split_for("pkg-1") == split_for("pkg-1")
    assert {split_for(f"pkg-{i}") for i in range(50)} == {"dev", "holdout"}


def test_init_drafts_labels_and_field_slots():
    names = [f"ext/{p}_{label}" for p in ("p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8")
             for label in ("spp", "invoice", "faktur", "kuitansi")] + ["ext/p1_bapp", "int/q1_unmapped_label"]
    manifest = init_manifest(files(*names), field_packages=2,
                             schema_fields={"INVOICE": ["total_amount"], "PAYMENT_REQUEST": ["requested_amount"]})
    validate_manifest(manifest)
    docs = {d["doc_key"]: d for d in manifest["documents"]}
    assert docs["ext/p1_spp"]["expected_type"] == "PAYMENT_REQUEST" and docs["ext/p1_spp"]["type_status"] == "draft"
    assert docs["ext/p1_faktur"]["type_status"] == "needs_review"
    assert docs["ext/p1_bapp"]["expected_type"] is None and docs["ext/p1_bapp"]["type_status"] == "needs_review"
    assert docs["int/q1_unmapped_label"]["type_status"] == "needs_review"
    with_fields = {d["package"] for d in docs.values() if d["fields"]}
    assert len(with_fields) <= 2 and all(split_for(p) == "holdout" for p in with_fields)
    for doc in docs.values():
        if doc["fields"]:
            assert all(slot == {"value": None, "status": "todo"} for slot in doc["fields"].values())


def test_manifest_validation():
    with pytest.raises(ValueError, match="MANIFEST_SCHEMA_UNSUPPORTED"):
        validate_manifest({"schema": "x", "documents": []})
    manifest = init_manifest(files("ext/p1_invoice"))
    manifest["documents"].append(dict(manifest["documents"][0]))
    with pytest.raises(ValueError, match="DUPLICATE_DOC_KEY"):
        validate_manifest(manifest)


def manifest_with(*docs):
    return {"schema": "tlkdoc.eval-manifest/v1", "documents": [
        {"doc_key": key, "path": f"/x/{key}.pdf", "group": "g", "package": key.split("_")[0], "label": "l",
         "split": split, "expected_type": expected, "type_status": status, "fields": fields}
        for key, expected, status, split, fields in docs]}


def test_classification_metrics_and_out_of_taxonomy_abstention():
    manifest = manifest_with(
        ("a_inv", "INVOICE", "verified", "dev", {}),
        ("b_inv", "INVOICE", "verified", "dev", {}),
        ("c_rcp", "RECEIPT", "verified", "holdout", {}),
        ("d_npwp", "TAX_REGISTRATION_CERTIFICATE", "verified", "dev", {}),  # not in taxonomy → expect UNKNOWN
        ("e_spp", "PAYMENT_REQUEST", "draft", "dev", {}),
        ("f_bapp", None, "needs_review", "dev", {}),
    )
    predictions = {"a_inv": {"document_type": "INVOICE", "status": "COMPLETED"},
                   "b_inv": {"document_type": "UNKNOWN", "status": "COMPLETED"},
                   "c_rcp": {"document_type": "INVOICE", "status": "COMPLETED"},
                   "d_npwp": {"document_type": "UNKNOWN", "status": "COMPLETED"},
                   "e_spp": {"document_type": "PAYMENT_REQUEST", "status": "COMPLETED"},
                   "f_bapp": {"document_type": "PAYMENT_REQUEST", "status": "COMPLETED"}}
    report = score(manifest, predictions, value_types=TYPES, normalize=fake_normalize,
                   options=ScoreOptions(taxonomy=TAXONOMY))
    c = report["classification"]
    assert (c["scored"], c["correct"], c["wrong_not_unknown"], c["abstained_wrongly"]) == (4, 2, 1, 1)
    assert c["per_class"]["INVOICE"] == {"support": 2, "tp": 1, "fp": 1, "fn": 1, "precision": 0.5, "recall": 0.5}
    assert c["per_class"]["UNKNOWN"]["tp"] == 1
    assert {"expected": "RECEIPT", "predicted": "INVOICE", "count": 1} in c["confusion"]
    with_drafts = score(manifest, predictions, value_types=TYPES, normalize=fake_normalize,
                        options=ScoreOptions(taxonomy=TAXONOMY, include_draft=True))
    assert with_drafts["classification"]["scored"] == 5  # needs_review is never scored
    holdout = score(manifest, predictions, value_types=TYPES, normalize=fake_normalize,
                    options=ScoreOptions(taxonomy=TAXONOMY, split="holdout"))
    assert holdout["classification"]["scored"] == 1


def test_field_outcomes_in_canonical_form():
    fields = {"total_amount": {"value": "1250000.00", "status": "verified"},
              "document_date": {"value": "2026-07-15", "status": "verified"},
              "tax_id": {"value": "01.234.567.8-901.000", "status": "verified"},
              "issuer_name": {"value": "PT Contoh Sintetis", "status": "verified"},
              "document_number": {"value": None, "status": "verified"},  # truly absent
              "subject": {"value": "x", "status": "todo"}}  # not scored
    manifest = manifest_with(("a_inv", "INVOICE", "verified", "dev", fields))
    predicted = [
        {"field_name": "total_amount", "value_type": "money", "state": "PRESENT", "raw_value": "Rp 1.250.000,00"},
        {"field_name": "document_date", "value_type": "date", "state": "PRESENT", "raw_value": "15 Juli 2026"},
        {"field_name": "tax_id", "value_type": "tax_id", "state": "PRESENT", "raw_value": "01.234.567.8-901.999"},
        {"field_name": "issuer_name", "value_type": "string", "state": "MISSING", "raw_value": None},
        {"field_name": "document_number", "value_type": "identifier", "state": "PRESENT", "raw_value": "INV-9"},
    ]
    report = score(manifest, {"a_inv": {"document_type": "INVOICE", "status": "COMPLETED", "fields": predicted}},
                   value_types=TYPES, normalize=fake_normalize, options=ScoreOptions(taxonomy=TAXONOMY))
    per = report["fields"]["per_field"]
    assert per["total_amount"]["correct"] == 1 and per["document_date"]["correct"] == 1
    assert per["tax_id"]["wrong"] == 1 and per["issuer_name"]["missed"] == 1
    assert per["document_number"]["false_present"] == 1 and "subject" not in per
    total = report["fields"]["total"]
    assert (total["correct"], total["precision"], total["recall"]) == (2, 0.5, 0.5)
    assert "total_amount" in format_report(report)


def test_loose_text():
    assert loose_text("  PT. Contoh  Sintetis, Tbk ") == loose_text("pt contoh sintetis tbk")


def test_cli_init_and_score(tmp_path, capsys):
    from edi_reference import cli

    samples = tmp_path / "samples" / "ext"
    samples.mkdir(parents=True)
    for name in ("p1_invoice", "p1_kuitansi", "p2_invoice"):
        (samples / f"{name}.pdf").write_bytes(b"%PDF-1.4 synthetic")
    manifest_path = tmp_path / "manifest.json"
    assert cli.main(["eval", "init", str(tmp_path / "samples"), "--out", str(manifest_path)]) == 0
    assert cli.main(["eval", "init", str(tmp_path / "samples"), "--out", str(manifest_path)]) == 2  # no silent overwrite
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for doc in manifest["documents"]:
        doc["type_status"] = "verified"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    predictions = tmp_path / "pred.jsonl"
    predictions.write_text("\n".join(json.dumps({"doc_key": d["doc_key"], "status": "COMPLETED",
                                                 "document_type": "INVOICE", "fields": []})
                                     for d in manifest["documents"]) + "\n", encoding="utf-8")
    report = tmp_path / "report.json"
    capsys.readouterr()
    assert cli.main(["eval", "score", "--manifest", str(manifest_path), "--predictions", str(predictions),
                     "--state-dir", str(tmp_path / "none"), "--report", str(report)]) == 0
    out = capsys.readouterr().out
    assert "classification: 2/3 correct" in out
    assert json.loads(report.read_text(encoding="utf-8"))["classification"]["wrong_not_unknown"] == 1


def test_review_sheet_round_trip(tmp_path):
    from edi_reference import cli

    manifest = manifest_with(("a_inv", "INVOICE", "draft", "dev",
                              {"total_amount": {"value": "100.00", "status": "draft"},
                               "tax_id": {"value": None, "status": "todo"}}),
                             ("b_bapp", None, "needs_review", "dev", {}))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    sheet = tmp_path / "review.csv"
    assert cli.main(["eval", "review-export", "--manifest", str(path), "--out", str(sheet)]) == 0
    lines = sheet.read_text(encoding="utf-8-sig").splitlines()
    assert lines[0] == "doc_key,kind,name,value,status,note,verified" and len(lines) == 5
    # a spreadsheet in an Indonesian locale saves with ';'
    edited = ["doc_key;kind;name;value;status;note;verified",
              "a_inv;type;expected_type;INVOICE;draft;;y",
              "a_inv;field;total_amount;125.00;draft;corrected;y",
              "a_inv;field;tax_id;;todo;;y",
              "b_bapp;type;expected_type;PAYMENT_REPORT;needs_review;isi berita acara pembayaran;"]
    sheet.write_text("\n".join(edited) + "\n", encoding="utf-8-sig")
    assert cli.main(["eval", "review-import", str(sheet), "--manifest", str(path)]) == 0
    docs = {d["doc_key"]: d for d in json.loads(path.read_text(encoding="utf-8"))["documents"]}
    assert (docs["a_inv"]["expected_type"], docs["a_inv"]["type_status"]) == ("INVOICE", "verified")
    assert docs["a_inv"]["fields"]["total_amount"] == {"value": "125.00", "status": "verified", "note": "corrected"}
    assert docs["a_inv"]["fields"]["tax_id"] == {"value": None, "status": "verified"}  # verified as absent
    assert (docs["b_bapp"]["expected_type"], docs["b_bapp"]["type_status"]) == ("PAYMENT_REPORT", "needs_review")
    assert docs["b_bapp"]["type_note"] == "isi berita acara pembayaran"


def test_money_compares_by_value_not_by_printed_precision():
    manifest = manifest_with(("a_inv", "INVOICE", "verified", "dev",
                              {"total_amount": {"value": "58739868.00", "status": "verified"}}))
    predicted = [{"field_name": "total_amount", "value_type": "money", "state": "PRESENT", "raw_value": "58.739.868"}]
    report = score(manifest, {"a_inv": {"document_type": "INVOICE", "status": "COMPLETED", "fields": predicted}},
                   value_types=TYPES, normalize=lambda value_type, raw: raw.replace(".", ""),
                   options=ScoreOptions(taxonomy=TAXONOMY))
    assert report["fields"]["per_field"]["total_amount"]["correct"] == 1
