"""Run the final extractor on the four unlabelled sample reports for qualitative review.

From the project root:
    py -3 unlabelled_review.py

Predictions and latency are saved under eval/unlabelled_review/. There are no gold
labels for these reports, so this runner intentionally does not calculate accuracy.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPORT_IDS = ["report_04", "report_07", "report_10", "report_12"]
DEFAULT_MODEL = "gemini-3.5-flash-lite"
MODEL = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
RUN_DIR = ROOT / "eval" / "unlabelled_review"


def add_poppler_to_path(env: dict[str, str]) -> None:
    """Find the common WinGet Poppler installation on Windows if needed."""
    entries = env.get("PATH", "").split(os.pathsep)
    if any((Path(entry) / "pdftoppm.exe").exists() or (Path(entry) / "pdftoppm").exists()
           for entry in entries if entry):
        return
    local_app_data = Path(env.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    package_dir = local_app_data / "Microsoft" / "WinGet" / "Packages" / (
        "oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    for candidate in sorted(package_dir.glob("poppler-*/Library/bin"), reverse=True):
        if (candidate / "pdftoppm.exe").exists():
            env["PATH"] = str(candidate) + os.pathsep + env.get("PATH", "")
            return


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    reports: dict[str, Path] = {}
    for report_id in REPORT_IDS:
        candidates = [ROOT / "reports" / f"{report_id}.pdf", ROOT / "reports" / f"{report_id}.jpg"]
        report_path = next((p for p in candidates if p.exists()), None)
        if report_path is None:
            print(f"Missing report file for {report_id}.", file=sys.stderr)
            return 2
        reports[report_id] = report_path

    key = getpass.getpass("Gemini API key (hidden): ").strip()
    if not key:
        print("No API key entered; stopping without API calls.", file=sys.stderr)
        return 2

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = key
    env["GEMINI_MODEL"] = MODEL
    add_poppler_to_path(env)

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "model": MODEL,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Qualitative review only; these four reports have no supplied gold labels.",
        "reports": {},
    }

    print(f"Model: {MODEL}")
    print(f"Output folder: {RUN_DIR.relative_to(ROOT)}")
    print("Running the final extractor on the four unlabelled reports. Review output against each source manually.\n")

    for report_id, report_path in reports.items():
        output_path = RUN_DIR / f"{report_id}.json"
        print(f"Running {report_id} ({report_path.name})...", flush=True)
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "extract.py"), str(report_path)],
                capture_output=True,
                text=True,
                env=env,
                timeout=240,
                cwd=ROOT,
            )
            elapsed = time.perf_counter() - start
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "Extractor failed without a message.").strip()
                manifest["reports"][report_id] = {
                    "status": "error", "latency_seconds": round(elapsed, 3), "error": message[:1200]
                }
                print(f"  FAILED after {elapsed:.1f}s: {message[:300]}")
                continue

            prediction = json.loads(completed.stdout)
            if not isinstance(prediction, dict) or not isinstance(prediction.get("tests"), list):
                raise ValueError("stdout was not a JSON object with a tests array")
            write_json(output_path, prediction)
            manifest["reports"][report_id] = {
                "status": "success",
                "latency_seconds": round(elapsed, 3),
                "source_file": str(report_path.relative_to(ROOT)),
                "output_file": str(output_path.relative_to(ROOT)),
                "extracted_rows": len(prediction["tests"]),
            }
            print(f"  OK: {len(prediction['tests'])} rows in {elapsed:.1f}s")
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error", "latency_seconds": round(elapsed, 3),
                "error": "Extractor exceeded the 240-second timeout."
            }
            print(f"  FAILED: timed out after {elapsed:.1f}s")
        except Exception as exc:
            elapsed = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error", "latency_seconds": round(elapsed, 3),
                "error": f"{type(exc).__name__}: {exc}"
            }
            print(f"  FAILED: {type(exc).__name__}: {exc}")
        write_json(RUN_DIR / "manifest.json", manifest)

    successes = [v for v in manifest["reports"].values() if v.get("status") == "success"]
    if successes:
        mean = sum(item["latency_seconds"] for item in successes) / len(successes)
        print(f"\nSuccessful reports: {len(successes)}/{len(REPORT_IDS)}")
        print(f"Mean latency: {mean:.2f}s/report")
    print(f"Saved outputs and manifest under {RUN_DIR.relative_to(ROOT)}.")
    print("No accuracy score is reported because these four reports have no gold labels.")
    return 0 if len(successes) == len(REPORT_IDS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
