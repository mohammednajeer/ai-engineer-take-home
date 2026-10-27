"""Controlled DPI experiment for the lab-report extractor.

Compares the committed 60-DPI reference-guard results with fresh 120-DPI
runs on two diagnostic reports (06 and 11). It does not modify extract.py.
Usage: py -3 dpi_experiment.py
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import score_eval

ROOT = Path(__file__).resolve().parent
MODEL = "gemini-3.5-flash-lite"
REPORT_IDS = ("report_06", "report_11")
BASELINE_DIR = ROOT / "eval" / "reference_guard"
OUTPUT_DIR = ROOT / "eval" / "dpi120_experiment"


def add_poppler_to_path(env: dict[str, str]) -> None:
    path_entries = env.get("PATH", "").split(os.pathsep)
    if any(
        (Path(entry) / "pdftoppm.exe").exists() or (Path(entry) / "pdftoppm").exists()
        for entry in path_entries if entry
    ):
        return

    local_app_data = Path(env.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    package_dir = local_app_data / "Microsoft" / "WinGet" / "Packages" / (
        "oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    for candidate in reversed(sorted(package_dir.glob("poppler-*/Library/bin"))):
        if (candidate / "pdftoppm.exe").exists():
            env["PATH"] = str(candidate) + os.pathsep + env.get("PATH", "")
            return


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    source_path = ROOT / "extract.py"
    if not source_path.exists():
        print("Run this script from the project root; extract.py is missing.", file=sys.stderr)
        return 2
    source = source_path.read_text(encoding="utf-8")
    if "DPI = 60" not in source:
        print("Expected 'DPI = 60' in extract.py; refusing to alter an unexpected source.", file=sys.stderr)
        return 2

    for report_id in REPORT_IDS:
        report_path = ROOT / "reports" / f"{report_id}.pdf"
        gold_path = ROOT / "gold" / f"{report_id}.json"
        baseline_path = BASELINE_DIR / f"{report_id}.json"
        if not report_path.exists() or not gold_path.exists() or not baseline_path.exists():
            print(f"Missing report, gold label, or 60-DPI prediction for {report_id}.", file=sys.stderr)
            return 2

    key = getpass.getpass("Gemini API key (hidden): ").strip()
    if not key:
        print("No API key entered; stopping without API calls.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = key
    env["GEMINI_MODEL"] = MODEL
    add_poppler_to_path(env)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    # Create an isolated copy of the current extractor with only DPI changed.
    # The checked-in extract.py remains untouched.
    with tempfile.TemporaryDirectory(prefix="lab-extract-dpi120-") as temporary_dir:
        experimental_extractor = Path(temporary_dir) / "extract_dpi120.py"
        experimental_extractor.write_text(source.replace("DPI = 60", "DPI = 120", 1), encoding="utf-8")

        for report_id in REPORT_IDS:
            output_path = OUTPUT_DIR / f"{report_id}.json"
            report_path = ROOT / "reports" / f"{report_id}.pdf"
            print(f"Running {report_id} at 120 DPI...", flush=True)
            started = time.perf_counter()
            try:
                completed = subprocess.run(
                    [sys.executable, str(experimental_extractor), str(report_path)],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=240,
                )
            except subprocess.TimeoutExpired:
                print(f"  FAILED: timed out after {time.perf_counter() - started:.1f}s")
                return 2

            latency = time.perf_counter() - started
            if completed.returncode != 0:
                print(f"  FAILED after {latency:.1f}s: {(completed.stderr or completed.stdout)[:600]}")
                return 2
            try:
                prediction = json.loads(completed.stdout)
            except json.JSONDecodeError as error:
                print(f"  FAILED: extractor did not return valid JSON: {error}", file=sys.stderr)
                return 2
            if not isinstance(prediction, dict) or not isinstance(prediction.get("tests"), list):
                print(f"  FAILED: {report_id} output is not an object containing a tests array.", file=sys.stderr)
                return 2
            output_path.write_text(json.dumps(prediction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            gold = read_json(ROOT / "gold" / f"{report_id}.json")
            base_pred = read_json(BASELINE_DIR / f"{report_id}.json")
            base_score = score_eval.score_report(report_id, gold, base_pred)
            new_score = score_eval.score_report(report_id, gold, prediction)
            results[report_id] = {
                "baseline_60_dpi": {
                    "predicted_rows": base_score["predicted_rows"],
                    "exact_rows": base_score["exact_rows"],
                    "gold_rows": base_score["gold_rows"],
                    "exact_row_recall": base_score["exact_row_recall"],
                },
                "experiment_120_dpi": {
                    "predicted_rows": new_score["predicted_rows"],
                    "exact_rows": new_score["exact_rows"],
                    "gold_rows": new_score["gold_rows"],
                    "exact_row_recall": new_score["exact_row_recall"],
                },
                "latency_120_dpi_seconds": round(latency, 3),
                "output_file": str(output_path.relative_to(ROOT)),
            }
            print(
                f"  OK: {len(prediction['tests'])} rows in {latency:.1f}s; "
                f"exact rows {new_score['exact_rows']}/{new_score['gold_rows']}"
            )

    baseline_latency: dict[str, float | None] = {}
    manifest_path = BASELINE_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        for report_id in REPORT_IDS:
            value = manifest.get("reports", {}).get(report_id, {}).get("latency_seconds")
            baseline_latency[report_id] = float(value) if value is not None else None
    else:
        baseline_latency = {report_id: None for report_id in REPORT_IDS}

    for report_id in REPORT_IDS:
        results[report_id]["latency_60_dpi_seconds"] = baseline_latency[report_id]

    baseline_gold = sum(results[r]["baseline_60_dpi"]["gold_rows"] for r in REPORT_IDS)
    baseline_exact = sum(results[r]["baseline_60_dpi"]["exact_rows"] for r in REPORT_IDS)
    dpi_gold = sum(results[r]["experiment_120_dpi"]["gold_rows"] for r in REPORT_IDS)
    dpi_exact = sum(results[r]["experiment_120_dpi"]["exact_rows"] for r in REPORT_IDS)
    baseline_times = [results[r]["latency_60_dpi_seconds"] for r in REPORT_IDS]
    baseline_times = [value for value in baseline_times if value is not None]
    experiment_times = [results[r]["latency_120_dpi_seconds"] for r in REPORT_IDS]

    summary = {
        "experiment": "Increase PDF rendering DPI from 60 to 120",
        "model": MODEL,
        "reports": list(REPORT_IDS),
        "control": "Saved reference_guard predictions from the same extractor/prompt/model at 60 DPI",
        "important_caveat": "Generative outputs can vary between calls; this is a small two-report diagnostic, not a full-dataset controlled estimate.",
        "aggregate_60_dpi": {
            "gold_rows": baseline_gold,
            "exact_rows": baseline_exact,
            "exact_row_recall": baseline_exact / baseline_gold if baseline_gold else 0.0,
            "mean_latency_seconds": round(sum(baseline_times) / len(baseline_times), 3) if baseline_times else None,
        },
        "aggregate_120_dpi": {
            "gold_rows": dpi_gold,
            "exact_rows": dpi_exact,
            "exact_row_recall": dpi_exact / dpi_gold if dpi_gold else 0.0,
            "mean_latency_seconds": round(sum(experiment_times) / len(experiment_times), 3),
        },
        "per_report": results,
        "cost_note": "This script measures latency and accuracy, not provider billing. Use provider billing/usage data for cost.",
    }
    summary_path = OUTPUT_DIR / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print("\n=== DPI EXPERIMENT SUMMARY ===")
    print(f"60 DPI:  {baseline_exact}/{baseline_gold} exact rows ({summary['aggregate_60_dpi']['exact_row_recall']:.1%})")
    print(f"120 DPI: {dpi_exact}/{dpi_gold} exact rows ({summary['aggregate_120_dpi']['exact_row_recall']:.1%})")
    if baseline_times:
        print(f"Mean latency, 60 DPI:  {summary['aggregate_60_dpi']['mean_latency_seconds']:.2f}s/report")
    print(f"Mean latency, 120 DPI: {summary['aggregate_120_dpi']['mean_latency_seconds']:.2f}s/report")
    print(f"Saved predictions and summary to {OUTPUT_DIR.relative_to(ROOT)}")
    print("No project source file or gold label was modified by this experiment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
