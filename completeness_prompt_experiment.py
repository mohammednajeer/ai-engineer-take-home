"""Test whether an explicit second-pass completeness instruction helps on two reports.

Run from the project root:
    py -3 completeness_prompt_experiment.py

This experiment changes only the in-memory prompt, not extract.py. Results are
saved in eval/completeness_prompt/ and compared with eval/reference_guard/ using
the same alias-aware scoring helper.
"""
from __future__ import annotations

import getpass
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORT_IDS = ["report_06", "report_11"]
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
RUN_DIR = ROOT / "eval" / "completeness_prompt"
BASELINE_DIR = ROOT / "eval" / "reference_guard"
EXPERIMENT_INSTRUCTION = (
    "\n\nExperimental completeness-check instruction:\n"
    "After drafting the JSON, scan every provided page once more specifically for test rows not yet included. "
    "Add only test results visibly present in the report. Do not duplicate rows, infer missing results, or guess fields."
)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def add_poppler_to_path() -> None:
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if any((Path(entry) / "pdftoppm.exe").exists() or (Path(entry) / "pdftoppm").exists()
           for entry in entries if entry):
        return
    local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    package_dir = local_app_data / "Microsoft" / "WinGet" / "Packages" / (
        "oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    for candidate in sorted(package_dir.glob("poppler-*/Library/bin"), reverse=True):
        if (candidate / "pdftoppm.exe").exists():
            os.environ["PATH"] = str(candidate) + os.pathsep + os.environ.get("PATH", "")
            return


def main() -> int:
    for report_id in REPORT_IDS:
        source = ROOT / "reports" / f"{report_id}.pdf"
        gold = ROOT / "gold" / f"{report_id}.json"
        baseline = BASELINE_DIR / f"{report_id}.json"
        if not source.exists() or not gold.exists() or not baseline.exists():
            print(f"Missing required source, gold label, or reference_guard prediction for {report_id}.")
            return 2

    key = getpass.getpass("Gemini API key (hidden): ").strip()
    if not key:
        print("No API key entered; stopping without API calls.")
        return 2

    os.environ["GEMINI_API_KEY"] = key
    os.environ["GEMINI_MODEL"] = MODEL
    add_poppler_to_path()

    # Import after selecting model and setting local credentials.
    import extract  # type: ignore
    import score_eval  # type: ignore

    if extract.MODEL != MODEL:
        print(f"Model mismatch: extract module uses {extract.MODEL}, runner expects {MODEL}.")
        return 2

    original_prompt = extract.PROMPT
    extract.PROMPT = original_prompt + EXPERIMENT_INSTRUCTION
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "model": MODEL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "hypothesis": "An explicit second-pass completeness check may recover omitted rows without changing the extraction pipeline.",
        "reports": {},
        "experimental_instruction": EXPERIMENT_INSTRUCTION.strip(),
        "note": "Small two-report experiment only; not a full benchmark. The source extractor and supplied gold labels are unchanged.",
    }

    latencies: list[float] = []
    print(f"Model: {MODEL}")
    print(f"Output folder: {RUN_DIR.relative_to(ROOT)}")
    print("Testing two reports with one extra prompt instruction; this makes two API requests.\n")

    for report_id in REPORT_IDS:
        source = ROOT / "reports" / f"{report_id}.pdf"
        gold_doc = score_eval.load_json(ROOT / "gold" / f"{report_id}.json")
        baseline_doc = score_eval.load_json(BASELINE_DIR / f"{report_id}.json")

        print(f"Running {report_id}...")
        start = time.perf_counter()
        prediction = extract.extract(source)
        latency = time.perf_counter() - start
        latencies.append(latency)

        output_path = RUN_DIR / f"{report_id}.json"
        write_json(output_path, prediction)
        baseline_score = score_eval.score_report(report_id, gold_doc, baseline_doc)
        experiment_score = score_eval.score_report(report_id, gold_doc, prediction)
        summary["reports"][report_id] = {
            "latency_seconds": round(latency, 3),
            "baseline_exact_rows": baseline_score["exact_rows"],
            "experiment_exact_rows": experiment_score["exact_rows"],
            "gold_rows": experiment_score["gold_rows"],
            "baseline_exact_row_recall": round(baseline_score["exact_row_recall"], 4),
            "experiment_exact_row_recall": round(experiment_score["exact_row_recall"], 4),
            "baseline_name_matched_rows": baseline_score["name_matched_rows"],
            "experiment_name_matched_rows": experiment_score["name_matched_rows"],
            "missing_gold_names": experiment_score["missing_gold_names"],
            "extra_predicted_names": experiment_score["extra_predicted_names"],
            "field_mismatches": experiment_score["field_mismatches"],
            "output_file": str(output_path.relative_to(ROOT)),
        }
        print(
            f"  baseline exact rows {baseline_score['exact_rows']}/{baseline_score['gold_rows']} -> "
            f"experiment {experiment_score['exact_rows']}/{experiment_score['gold_rows']} "
            f"in {latency:.1f}s"
        )

    summary["mean_latency_seconds"] = round(sum(latencies) / len(latencies), 3)
    write_json(RUN_DIR / "summary.json", summary)
    print(f"\nMean experiment latency: {summary['mean_latency_seconds']:.2f}s/report")
    print(f"Saved predictions and summary under {RUN_DIR.relative_to(ROOT)}.")
    print("Review the two-report sample size and all field mismatches before drawing conclusions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
