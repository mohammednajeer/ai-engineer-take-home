"""Score saved lab-report predictions against supplied gold labels without API calls.

Usage from the project root:
    py -3 score_eval.py eval/baseline
    py -3 score_eval.py eval/improved

Writes metrics_alias_aware.json into the prediction directory. The supplied gold
files are read-only. A small, explicit alias map handles observed equivalent
lab-test names; all aliases are documented here and should be reviewed before use.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LABELLED_REPORTS = [
    "report_01", "report_02", "report_03", "report_05",
    "report_06", "report_08", "report_09", "report_11",
]
FIELDS = ("value", "unit", "reference_range")

# Conservative aliases based on naming variants observed in the supplied reports.
# Keys and values are compact normalized strings (lowercase alphanumeric only).
ALIASES = {
    # Common spelling / abbreviation variants
    "haemoglobin": "hemoglobin",
    "hemoglobinhb": "hemoglobin",
    "packedcellvolume": "pcv",
    "packedcellvolumepcv": "pcv",
    "pcv": "pcv",
    "tshultrasensitive": "tsh",
    "vitdtotal": "vitamindtotal",
    "vitb12": "vitaminb12",
    "fbs": "fastingbloodsugar",
    "ppbs": "postprandialbloodsugar",
    "glycatedhb": "hba1c",
    "glycosylatedhemoglobinhba1c": "hba1c",
    "glycatedhaemoglobinhba1c": "hba1c",
    # Urine-report labels: generic label and explicit "Urine ..." label
    "urinecolor": "color",
    "urineclarity": "clarity",
    "appearance": "clarity",
    "reactionph": "ph",
    "urineph": "ph",
    "specificgravity": "specificgravity",
    "spgravity": "specificgravity",
    "urinespecificgravity": "specificgravity",
    "urinealbumin": "albumin",
    "sugar": "urinesugar",
    "urinesugar": "urinesugar",
    "urineglucose": "urinesugar",
    "ketonebodies": "ketones",
    "urineketones": "ketones",
    "leucocytes": "leucocytes",
    "urineleucocytes": "leucocytes",
    "erythrocytes": "erythrocytes",
    "urineerythrocytes": "erythrocytes",
    "squamousepithelialcells": "squamousepithelialcells",
    "urinesquamousepithelialcells": "squamousepithelialcells",
    # Common equivalent lab-test names
    "crp": "creactiveprotein",
    "creactiveprotein": "creactiveprotein",
    "esrwestergren": "erythrocytesedimentationrate",
    "erythrocytesedimentationrate": "erythrocytesedimentationrate",
}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return data


def compact_name(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.replace("haemoglobin", "hemoglobin")
    return re.sub(r"[^a-z0-9]+", "", text)


def canonical_name(value: Any) -> str:
    compact = compact_name(value)
    return ALIASES.get(compact, compact)


def normalize_text(value: Any, *, remove_spaces: bool = False, remove_commas: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = text.replace("μ", "µ")
    if remove_commas:
        text = text.replace(",", "")
    text = re.sub(r"\s+", "" if remove_spaces else " ", text)
    return text


def numeric_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def value_equal(gold: Any, predicted: Any) -> bool:
    gold_num, pred_num = numeric_value(gold), numeric_value(predicted)
    if gold_num is not None and pred_num is not None:
        return math.isclose(gold_num, pred_num, rel_tol=0.0, abs_tol=0.01)
    return normalize_text(gold, remove_spaces=True) == normalize_text(predicted, remove_spaces=True)


def field_equal(field: str, gold: Any, predicted: Any) -> bool:
    if field == "value":
        return value_equal(gold, predicted)
    if field == "unit":
        return normalize_text(gold, remove_spaces=True) == normalize_text(predicted, remove_spaces=True)
    if field == "reference_range":
        # Removes thousands separators to treat "1,50,000 - 4,10,000" and
        # "150000 - 410000" as equivalent, while retaining comparison signs.
        return normalize_text(gold, remove_spaces=True, remove_commas=True) == normalize_text(
            predicted, remove_spaces=True, remove_commas=True
        )
    raise ValueError(f"Unexpected field: {field}")


def score_report(report_id: str, gold_doc: dict[str, Any], pred_doc: dict[str, Any]) -> dict[str, Any]:
    gold_rows = gold_doc.get("tests", [])
    pred_rows = pred_doc.get("tests", [])
    if not isinstance(gold_rows, list) or not isinstance(pred_rows, list):
        raise ValueError(f"{report_id}: expected a tests array in both gold and predictions")

    used_pred: set[int] = set()
    matched: list[tuple[int, int]] = []
    missing: list[str] = []
    for gidx, grow in enumerate(gold_rows):
        key = canonical_name(grow.get("test_name"))
        pidx = next((
            idx for idx, prow in enumerate(pred_rows)
            if idx not in used_pred and canonical_name(prow.get("test_name")) == key
        ), None)
        if pidx is None:
            missing.append(str(grow.get("test_name", "")))
        else:
            used_pred.add(pidx)
            matched.append((gidx, pidx))

    correct = {field: 0 for field in FIELDS}
    exact_rows = 0
    field_mismatches: list[dict[str, Any]] = []
    for gidx, pidx in matched:
        grow, prow = gold_rows[gidx], pred_rows[pidx]
        checks = {field: field_equal(field, grow.get(field), prow.get(field)) for field in FIELDS}
        for field, is_correct in checks.items():
            correct[field] += int(is_correct)
        exact_rows += int(all(checks.values()))
        if not all(checks.values()):
            field_mismatches.append({
                "gold_test_name": grow.get("test_name"),
                "predicted_test_name": prow.get("test_name"),
                "checks": checks,
                "gold_row": grow,
                "predicted_row": prow,
            })

    gold_count = len(gold_rows)
    pred_count = len(pred_rows)
    match_count = len(matched)
    denominator = match_count or 1
    extras = [
        str(row.get("test_name", ""))
        for idx, row in enumerate(pred_rows) if idx not in used_pred
    ]
    return {
        "report_id": report_id,
        "gold_rows": gold_count,
        "predicted_rows": pred_count,
        "name_matched_rows": match_count,
        "name_precision": match_count / pred_count if pred_count else 0.0,
        "name_recall": match_count / gold_count if gold_count else 0.0,
        "value_accuracy_on_name_matches": correct["value"] / denominator,
        "unit_accuracy_on_name_matches": correct["unit"] / denominator,
        "reference_range_accuracy_on_name_matches": correct["reference_range"] / denominator,
        "exact_rows": exact_rows,
        "exact_row_recall": exact_rows / gold_count if gold_count else 0.0,
        "field_correct_counts": correct,
        "missing_gold_names": missing,
        "extra_predicted_names": extras,
        "field_mismatches": field_mismatches,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prediction_dir", nargs="?", default="eval/baseline",
                        help="Folder containing report_XX.json prediction files (default: eval/baseline)")
    parser.add_argument("--output", default="metrics_alias_aware.json",
                        help="Summary JSON filename written inside prediction_dir")
    args = parser.parse_args()
    prediction_dir = (ROOT / args.prediction_dir).resolve()
    if not prediction_dir.is_dir():
        parser.error(f"Prediction directory does not exist: {prediction_dir}")

    per_report: list[dict[str, Any]] = []
    for report_id in LABELLED_REPORTS:
        gold_path = ROOT / "gold" / f"{report_id}.json"
        pred_path = prediction_dir / f"{report_id}.json"
        if not gold_path.exists():
            raise FileNotFoundError(f"Missing gold file: {gold_path}")
        if not pred_path.exists():
            raise FileNotFoundError(f"Missing prediction file: {pred_path}")
        result = score_report(report_id, load_json(gold_path), load_json(pred_path))
        per_report.append(result)
        print(
            f"{report_id}: gold={result['gold_rows']} predicted={result['predicted_rows']} "
            f"name-matched={result['name_matched_rows']} exact={result['exact_rows']} "
            f"recall={result['exact_row_recall']:.1%}"
        )

    gold_total = sum(r["gold_rows"] for r in per_report)
    pred_total = sum(r["predicted_rows"] for r in per_report)
    matched_total = sum(r["name_matched_rows"] for r in per_report)
    exact_total = sum(r["exact_rows"] for r in per_report)
    correct = {
        field: sum(r["field_correct_counts"][field] for r in per_report)
        for field in FIELDS
    }
    denominator = matched_total or 1
    summary = {
        "scoring_mode": "alias-aware; supplied gold labels unchanged",
        "prediction_dir": str(prediction_dir.relative_to(ROOT)),
        "labelled_reports": len(per_report),
        "gold_rows": gold_total,
        "predicted_rows": pred_total,
        "name_matched_rows": matched_total,
        "name_precision": matched_total / pred_total if pred_total else 0.0,
        "name_recall": matched_total / gold_total if gold_total else 0.0,
        "value_accuracy_on_name_matches": correct["value"] / denominator,
        "unit_accuracy_on_name_matches": correct["unit"] / denominator,
        "reference_range_accuracy_on_name_matches": correct["reference_range"] / denominator,
        "exact_rows": exact_total,
        "exact_row_recall": exact_total / gold_total if gold_total else 0.0,
        "field_correct_counts": correct,
        "metrics_definitions": {
            "name_precision": "matched test-name rows / predicted rows",
            "name_recall": "matched test-name rows / gold rows",
            "field_accuracy": "field matches among name-matched rows only",
            "exact_row_recall": "rows matching name, value, unit, and reference range / gold rows",
        },
        "alias_map_compact_keys": ALIASES,
        "per_report": per_report,
        "limitations": [
            "Scores are against supplied labels, which may contain errors; suspicious labels must be verified against the source report.",
            "The alias map only normalizes known naming variants and should be reviewed; do not add aliases just to raise scores.",
            "Value metrics use absolute numeric tolerance 0.01; non-numeric values compare as normalized strings.",
            "Latency and cost are measured separately from this scoring script.",
        ],
    }
    out_path = prediction_dir / args.output
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n=== ALIAS-AWARE AGGREGATE ===")
    print(f"Name precision: {summary['name_precision']:.1%}")
    print(f"Name recall: {summary['name_recall']:.1%}")
    print(f"Value accuracy (name-matched rows): {summary['value_accuracy_on_name_matches']:.1%}")
    print(f"Unit accuracy (name-matched rows): {summary['unit_accuracy_on_name_matches']:.1%}")
    print(f"Reference-range accuracy (name-matched rows): {summary['reference_range_accuracy_on_name_matches']:.1%}")
    print(f"Exact-row recall: {summary['exact_row_recall']:.1%} ({exact_total}/{gold_total})")
    print(f"Saved: {out_path.relative_to(ROOT)}")
    print("No API calls were made; gold files and raw predictions were not modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
