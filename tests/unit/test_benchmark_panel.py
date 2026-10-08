import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "benchmark_panel", Path(__file__).resolve().parents[2] / "scripts" / "benchmark_panel.py"
)
panel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(panel)


def doc(label, predicted, present=0, proposed=0, layer=None, error=None, llm_s=1.0):
    return {"label": label, "predicted": predicted, "present": present, "proposed": proposed,
            "in_text_layer": layer or {}, "fields": {}, "error": error, "llm_s": llm_s, "ocr_s": 2.0}


def test_summary_separates_abstention_from_wrong_labels():
    summary = panel.summarize([
        doc("INVOICE", "INVOICE", present=3, proposed=4, layer={"a": True, "b": False, "c": None}),
        doc("PAYMENT_REQUEST", "UNKNOWN"),
        doc("UNKNOWN", "PAYMENT_REQUEST"),
        doc(None, "RECEIPT"),
        doc("INVOICE", None, error="OCR failed"),
    ])

    assert (summary["labelled"], summary["correct"]) == (4, 1)
    assert summary["unknown"] == 1
    assert summary["wrong_not_unknown"] == 1
    assert summary["errors"] == 1
    assert (summary["fields_present"], summary["proposed"]) == (3, 4)
    assert (summary["text_layer_confirmed"], summary["text_layer_checked"]) == (1, 2)
    assert {"label": "UNKNOWN", "predicted": "PAYMENT_REQUEST", "count": 1} in summary["confusion"]


def test_text_layer_check_ignores_separators_and_skips_scans():
    assert panel.in_text_layer("Rp 1.250.000,00", "Total: Rp1.250.000,00") is True
    assert panel.in_text_layer("SYN-9", "nothing here") is False
    assert panel.in_text_layer("SYN-9", "   ") is None
