"""Audit baseline predictions against supplied gold labels without making API calls.

Run from the project root:
    py -3 audit_baseline.py

Writes eval/baseline/audit.json and prints mismatches that should be checked
against the original PDF/image. It never edits the supplied gold files.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
RUN_DIR = ROOT / "eval" / "baseline"
REPORT_IDS = [
    "report_01", "report_02", "report_03", "report_05",
    "report_06", "report_08", "report_09", "report_11",
]
FIELDS = ("value", "unit", "reference_range")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def normalize_name(value: Any) -> str:
    raw = str(value or "").strip().lower().replace("haemoglobin", "hemoglobin")
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    aliases = {
        "packedcellvolumepcv": "pcv",
        "packedcellvolume": "pcv",
        "pcv": "pcv",
    }
    return aliases.get(compact, compact)


def normalize_text(value: Any, remove_spaces: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", "" if remove_spaces else " ", text)


def values_equal(a: Any, b: Any) -> bool:
    def to_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    num_a, num_b = to_float(a), to_float(b)
    if num_a is not None and num_b is not None:
        return math.isclose(num_a, num_b, rel_tol=0.0, abs_tol=0.01)
    return normalize_text(a) == normalize_text(b)


def field_equal(field: str, gold_value: Any, pred_value: Any) -> bool:
    if field == "value":
        return values_equal(gold_value, pred_value)
    if field == "reference_range":
        return normalize_text(gold_value, remove_spaces=True) == normalize_text(pred_value, remove_spaces=True)
    return normalize_text(gold_value) == normalize_text(pred_value)


def audit_report(report_id: str) -> dict[str, Any]:
    gold_path = ROOT / "gold" / f"{report_id}.json"
    pred_path = RUN_DIR / f"{report_id}.json"
    if not gold_path.exists() or not pred_path.exists():
        raise FileNotFoundError(f"Missing {gold_path.name} or {pred_path.name}; run the baseline first.")

    gold = load_json(gold_path).get("tests", [])
    pred = load_json(pred_path).get("tests", [])
    used_pred: set[int] = set()
    matched: list[tuple[int, int]] = []
    missing_gold: list[dict[str, Any]] = []

    for gold_index, gold_row in enumerate(gold):
        normalized = normalize_name(gold_row.get("test_name"))
        pred_index = next((
            i for i, pred_row in enumerate(pred)
            if i not in used_pred and normalize_name(pred_row.get("test_name")) == normalized
        ), None)
        if pred_index is None:
            missing_gold.append({"test_name": gold_row.get("test_name", ""), "gold_row": gold_row})
        else:
            used_pred.add(pred_index)
            matched.append((gold_index, pred_index))

    field_mismatches: list[dict[str, Any]] = []
    exact_rows = 0
    for gold_index, pred_index in matched:
        gold_row, pred_row = gold[gold_index], pred[pred_index]
        mismatches = {}
        for field in FIELDS:
            g, p = gold_row.get(field), pred_row.get(field)
            if not field_equal(field, g, p):
                mismatches[field] = {"gold": g, "predicted": p}
        if not mismatches:
            exact_rows += 1
        else:
            field_mismatches.append({
                "test_name_gold": gold_row.get("test_name", ""),
                "test_name_predicted": pred_row.get("test_name", ""),
                "mismatches": mismatches,
                "gold_row": gold_row,
                "predicted_row": pred_row,
            })

    extra_pred = [
        {"test_name": row.get("test_name", ""), "predicted_row": row}
        for i, row in enumerate(pred) if i not in used_pred
    ]
    return {
        "report_id": report_id,
        "gold_rows": len(gold),
        "predicted_rows": len(pred),
        "name_matched_rows": len(matched),
        "exact_rows": exact_rows,
        "missing_gold_rows": missing_gold,
        "extra_predicted_rows": extra_pred,
        "field_mismatches": field_mismatches,
    }


def main() -> int:
    all_reports: list[dict[str, Any]] = []
    for report_id in REPORT_IDS:
        result = audit_report(report_id)
        all_reports.append(result)
        print(f"\n=== {report_id} ===")
        print(
            f"Gold {result['gold_rows']} | predicted {result['predicted_rows']} | "
            f"name matched {result['name_matched_rows']} | exact rows {result['exact_rows']}"
        )
        if result["missing_gold_rows"]:
            print("MISSING from prediction (check the PDF: could be missed by model OR absent/wrong in gold):")
            for item in result["missing_gold_rows"]:
                row = item["gold_row"]
                print(f"  - {row.get('test_name')} | value={row.get('value')} | unit={row.get('unit')} | range={row.get('reference_range')}")
        if result["extra_predicted_rows"]:
            print("EXTRA predictions (check the PDF and gold label):")
            for item in result["extra_predicted_rows"]:
                row = item["predicted_row"]
                print(f"  + {row.get('test_name')} | value={row.get('value')} | unit={row.get('unit')} | range={row.get('reference_range')}")
        if result["field_mismatches"]:
            print("FIELD mismatches on same-name rows (check the PDF first):")
            for item in result["field_mismatches"]:
                print(f"  ! {item['test_name_gold']}")
                for field, values in item["mismatches"].items():
                    print(f"      {field}: gold={values['gold']!r} | predicted={values['predicted']!r}")
        if not result["missing_gold_rows"] and not result["extra_predicted_rows"] and not result["field_mismatches"]:
            print("No mismatches under the current matching rules.")

    output_path = RUN_DIR / "audit.json"
    output_path.write_text(json.dumps({"reports": all_reports}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    totals = {
        "gold_rows": sum(r["gold_rows"] for r in all_reports),
        "predicted_rows": sum(r["predicted_rows"] for r in all_reports),
        "name_matched_rows": sum(r["name_matched_rows"] for r in all_reports),
        "exact_rows": sum(r["exact_rows"] for r in all_reports),
        "missing_gold_rows": sum(len(r["missing_gold_rows"]) for r in all_reports),
        "extra_predicted_rows": sum(len(r["extra_predicted_rows"]) for r in all_reports),
        "same_name_rows_with_field_mismatches": sum(len(r["field_mismatches"]) for r in all_reports),
    }
    print("\n=== TOTALS ===")
    for name, value in totals.items():
        print(f"{name}: {value}")
    print(f"\nDetailed audit saved to {output_path.relative_to(ROOT)}")
    print("This is a discrepancy report, not a verdict that the model or gold label is wrong. Verify suspicious rows against the original report image/PDF.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
