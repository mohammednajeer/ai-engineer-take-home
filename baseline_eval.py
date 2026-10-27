"""Run and score the unchanged lab-report extractor against supplied gold labels.

Usage from the project root:
    py -3 baseline_eval.py

The script prompts for the API key without echoing it, saves raw predictions and
latencies under eval/baseline/, and can resume after an interrupted run.
"""
from __future__ import annotations

import getpass
import json
import math
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
LABELLED_REPORTS = [
    "report_01", "report_02", "report_03", "report_05",
    "report_06", "report_08", "report_09", "report_11",
]
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
RUN_DIR = ROOT / "eval" / "baseline"


def add_poppler_to_path(env: dict[str, str]) -> None:
    """Find the user's WinGet Poppler installation if pdftoppm isn't already on PATH."""
    path_entries = env.get("PATH", "").split(os.pathsep)
    if any((Path(entry) / "pdftoppm.exe").exists() or (Path(entry) / "pdftoppm").exists()
           for entry in path_entries if entry):
        return

    local_app_data = Path(env.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    package_dir = local_app_data / "Microsoft" / "WinGet" / "Packages" / (
        "oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    candidates = sorted(package_dir.glob("poppler-*/Library/bin"))
    for candidate in reversed(candidates):
        if (candidate / "pdftoppm.exe").exists():
            env["PATH"] = str(candidate) + os.pathsep + env.get("PATH", "")
            return


def write_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_name(value: Any) -> str:
    """Normalize case/punctuation and a couple of standard spelling/name variants."""
    raw = str(value or "").strip().lower()
    raw = raw.replace("haemoglobin", "hemoglobin")
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    aliases = {
        "packedcellvolumepcv": "pcv",
        "packedcellvolume": "pcv",
        "pcv": "pcv",
    }
    return aliases.get(compact, compact)


def normalize_optional_text(value: Any, *, remove_spaces: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace("−", "-").replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text) if remove_spaces else re.sub(r"\s+", " ", text)
    return text


def values_equal(a: Any, b: Any) -> bool:
    def to_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    number_a, number_b = to_float(a), to_float(b)
    if number_a is not None and number_b is not None:
        return math.isclose(number_a, number_b, rel_tol=0.0, abs_tol=0.01)
    return normalize_optional_text(a) == normalize_optional_text(b)


def field_matches(gold_row: dict[str, Any], pred_row: dict[str, Any]) -> dict[str, bool]:
    return {
        "value": values_equal(gold_row.get("value"), pred_row.get("value")),
        "unit": normalize_optional_text(gold_row.get("unit")) == normalize_optional_text(pred_row.get("unit")),
        "reference_range": normalize_optional_text(
            gold_row.get("reference_range"), remove_spaces=True
        ) == normalize_optional_text(pred_row.get("reference_range"), remove_spaces=True),
    }


def score_one(gold: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
    gold_rows = gold.get("tests", [])
    pred_rows = pred.get("tests", [])
    used_pred_indices: set[int] = set()
    matched_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    missing_names = []

    # Match rows by normalized test name, without allowing one prediction to
    # satisfy multiple gold rows. Do not match on values, which could hide errors.
    for gold_row in gold_rows:
        expected_name = normalize_name(gold_row.get("test_name"))
        match_index = next(
            (index for index, pred_row in enumerate(pred_rows)
             if index not in used_pred_indices
             and normalize_name(pred_row.get("test_name")) == expected_name),
            None,
        )
        if match_index is None:
            missing_names.append(gold_row.get("test_name", ""))
            continue
        used_pred_indices.add(match_index)
        matched_rows.append((gold_row, pred_rows[match_index]))

    field_correct = {"value": 0, "unit": 0, "reference_range": 0}
    exact_rows = 0
    for gold_row, pred_row in matched_rows:
        fields = field_matches(gold_row, pred_row)
        for field, correct in fields.items():
            field_correct[field] += int(correct)
        exact_rows += int(all(fields.values()))

    gold_count = len(gold_rows)
    pred_count = len(pred_rows)
    matched_count = len(matched_rows)
    matched_field_denominator = matched_count or 1
    return {
        "gold_rows": gold_count,
        "predicted_rows": pred_count,
        "name_matched_rows": matched_count,
        "missing_gold_names": missing_names,
        "extra_predicted_names": [
            row.get("test_name", "") for index, row in enumerate(pred_rows)
            if index not in used_pred_indices
        ],
        "name_precision": matched_count / pred_count if pred_count else 0.0,
        "name_recall": matched_count / gold_count if gold_count else 0.0,
        "value_accuracy_on_name_matches": field_correct["value"] / matched_field_denominator,
        "unit_accuracy_on_name_matches": field_correct["unit"] / matched_field_denominator,
        "reference_range_accuracy_on_name_matches": field_correct["reference_range"] / matched_field_denominator,
        "exact_row_recall": exact_rows / gold_count if gold_count else 0.0,
        "exact_rows": exact_rows,
        "field_correct_counts": field_correct,
    }


def aggregate(per_report: dict[str, dict[str, Any]]) -> dict[str, Any]:
    gold_rows = sum(result["gold_rows"] for result in per_report.values())
    pred_rows = sum(result["predicted_rows"] for result in per_report.values())
    matched = sum(result["name_matched_rows"] for result in per_report.values())
    exact = sum(result["exact_rows"] for result in per_report.values())
    matched_denominator = matched or 1
    field_counts = {
        field: sum(result["field_correct_counts"][field] for result in per_report.values())
        for field in ("value", "unit", "reference_range")
    }
    return {
        "labelled_reports": len(per_report),
        "gold_rows": gold_rows,
        "predicted_rows": pred_rows,
        "name_matched_rows": matched,
        "name_precision": matched / pred_rows if pred_rows else 0.0,
        "name_recall": matched / gold_rows if gold_rows else 0.0,
        "value_accuracy_on_name_matches": field_counts["value"] / matched_denominator,
        "unit_accuracy_on_name_matches": field_counts["unit"] / matched_denominator,
        "reference_range_accuracy_on_name_matches": field_counts["reference_range"] / matched_denominator,
        "exact_rows": exact,
        "exact_row_recall": exact / gold_rows if gold_rows else 0.0,
        "field_correct_counts": field_counts,
        "metric_notes": [
            "Names are normalized for case, punctuation, haemoglobin/hemoglobin spelling, and PCV alias.",
            "Numeric values use an absolute tolerance of 0.01; units are compared case-insensitively.",
            "Reference ranges ignore whitespace and normalize dash characters.",
            "Field accuracies are among rows whose test names matched; missing/extra rows are reflected in name recall/precision.",
            "These are raw scores against the supplied gold labels; label issues must be documented separately, not silently edited.",
        ],
    }


def main() -> int:
    for report_id in LABELLED_REPORTS:
        report = ROOT / "reports" / f"{report_id}.pdf"
        if not report.exists():
            report = ROOT / "reports" / f"{report_id}.jpg"
        label = ROOT / "gold" / f"{report_id}.json"
        if not report.exists() or not label.exists():
            print(f"Missing report or gold label for {report_id}.", file=sys.stderr)
            return 2

    key = getpass.getpass("Gemini API key (hidden): ").strip()
    if not key:
        print("No API key entered; stopping without making API calls.", file=sys.stderr)
        return 2

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RUN_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("model") != MODEL:
            print(
                f"This baseline folder already uses {manifest.get('model')!r}, not {MODEL!r}. "
                "Do not mix models in one baseline. Use the original model or create a separate run folder.",
                file=sys.stderr,
            )
            return 2
    else:
        manifest = {
            "model": MODEL,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "reports": {},
        }

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = key
    env["GEMINI_MODEL"] = MODEL
    add_poppler_to_path(env)

    print(f"Model: {MODEL}")
    print(f"Output folder: {RUN_DIR.relative_to(ROOT)}")
    print("Running the unchanged extractor on the 8 labelled reports. Successful reports are saved and reused on retry.\n")

    for report_id in LABELLED_REPORTS:
        output_path = RUN_DIR / f"{report_id}.json"
        previous = manifest["reports"].get(report_id, {})
        if previous.get("status") == "success" and output_path.exists():
            print(f"{report_id}: reusing saved successful result ({previous.get('latency_seconds', '?')} s)")
            continue

        report = ROOT / "reports" / f"{report_id}.pdf"
        if not report.exists():
            report = ROOT / "reports" / f"{report_id}.jpg"
        print(f"Running {report_id}...", flush=True)
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "extract.py"), str(report)],
                capture_output=True,
                text=True,
                env=env,
                timeout=240,
                cwd=ROOT,
            )
            latency = time.perf_counter() - start
            if completed.returncode != 0:
                error_text = (completed.stderr or completed.stdout or "Extractor failed without an error message.").strip()
                manifest["reports"][report_id] = {
                    "status": "error",
                    "latency_seconds": round(latency, 3),
                    "error": error_text[:1200],
                }
                write_json(manifest_path, manifest)
                print(f"  FAILED after {latency:.1f}s: {error_text[:350]}")
                continue

            prediction = json.loads(completed.stdout)
            if not isinstance(prediction, dict) or not isinstance(prediction.get("tests"), list):
                raise ValueError("Extractor stdout was not a JSON object with a tests array.")
            write_json(output_path, prediction)
            manifest["reports"][report_id] = {
                "status": "success",
                "latency_seconds": round(latency, 3),
                "report_file": str(report.relative_to(ROOT)),
                "output_file": str(output_path.relative_to(ROOT)),
            }
            write_json(manifest_path, manifest)
            print(f"  OK: {len(prediction['tests'])} extracted rows in {latency:.1f}s")
        except subprocess.TimeoutExpired:
            latency = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error",
                "latency_seconds": round(latency, 3),
                "error": "Extractor exceeded the 240-second evaluation timeout.",
            }
            write_json(manifest_path, manifest)
            print(f"  FAILED: timed out after {latency:.1f}s")
        except Exception as error:
            latency = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error",
                "latency_seconds": round(latency, 3),
                "error": f"{type(error).__name__}: {error}",
            }
            write_json(manifest_path, manifest)
            print(f"  FAILED: {type(error).__name__}: {error}")

    successful_ids = [
        report_id for report_id in LABELLED_REPORTS
        if manifest.get("reports", {}).get(report_id, {}).get("status") == "success"
        and (RUN_DIR / f"{report_id}.json").exists()
    ]
    if len(successful_ids) != len(LABELLED_REPORTS):
        failed_ids = [report_id for report_id in LABELLED_REPORTS if report_id not in successful_ids]
        print("\nBaseline is incomplete; no aggregate accuracy score has been reported yet.")
        print("Failed reports:", ", ".join(failed_ids))
        print("Rerun `py -3 baseline_eval.py` to retry failures; successful results are reused.")
        return 2

    per_report: dict[str, dict[str, Any]] = {}
    for report_id in LABELLED_REPORTS:
        gold_path = ROOT / "gold" / f"{report_id}.json"
        pred_path = RUN_DIR / f"{report_id}.json"
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        pred = json.loads(pred_path.read_text(encoding="utf-8"))
        per_report[report_id] = score_one(gold, pred)

    summary = {
        "model": MODEL,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "latency_seconds": {
            report_id: manifest["reports"][report_id]["latency_seconds"]
            for report_id in LABELLED_REPORTS
        },
        "latency_mean_seconds": round(
            sum(manifest["reports"][report_id]["latency_seconds"] for report_id in LABELLED_REPORTS)
            / len(LABELLED_REPORTS), 3
        ),
        "latency_median_seconds": round(sorted(
            manifest["reports"][report_id]["latency_seconds"] for report_id in LABELLED_REPORTS
        )[len(LABELLED_REPORTS) // 2 - (1 if len(LABELLED_REPORTS) % 2 == 0 else 0)]
        if len(LABELLED_REPORTS) % 2 else (
            sorted(manifest["reports"][report_id]["latency_seconds"] for report_id in LABELLED_REPORTS)[3]
            + sorted(manifest["reports"][report_id]["latency_seconds"] for report_id in LABELLED_REPORTS)[4]
        ) / 2, 3),
        "per_report": per_report,
        "aggregate": aggregate(per_report),
        "cost_note": "This runner records latency, not provider billing. Record actual spend from the provider dashboard or calculate an estimate from current model pricing and usage; do not assume cost is zero.",
    }
    write_json(RUN_DIR / "summary.json", summary)

    print("\nBaseline evaluation complete")
    print(f"Model: {MODEL}")
    print(f"Mean latency: {summary['latency_mean_seconds']:.2f}s/report")
    agg = summary["aggregate"]
    print(f"Rows: {agg['name_matched_rows']}/{agg['gold_rows']} gold rows matched by test name")
    print(f"Name precision: {agg['name_precision']:.1%}")
    print(f"Name recall: {agg['name_recall']:.1%}")
    print(f"Value accuracy among name-matched rows: {agg['value_accuracy_on_name_matches']:.1%}")
    print(f"Unit accuracy among name-matched rows: {agg['unit_accuracy_on_name_matches']:.1%}")
    print(f"Reference-range accuracy among name-matched rows: {agg['reference_range_accuracy_on_name_matches']:.1%}")
    print(f"Exact-row recall against supplied labels: {agg['exact_row_recall']:.1%}")
    print("\nSaved raw predictions, timings, and scores under eval/baseline/.")
    print("Remember: these are raw scores against supplied labels. Audit label problems separately; do not silently edit gold files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
