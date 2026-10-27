"""Final extraction run with token usage and paid-tier cost estimates.

Run from the project root:
    py -3 final_eval.py

Requires extract.py to emit a GEMINI_USAGE_JSON record to stderr, as described
in the assessment instructions. Raw predictions are saved under eval/final/.
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
REPORT_IDS = [
    "report_01", "report_02", "report_03", "report_05",
    "report_06", "report_08", "report_09", "report_11",
]
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
RUN_DIR = ROOT / "eval" / "final"
# Standard paid-tier rates from the official Gemini API pricing page,
# checked 27 October 2026. This estimates paid-tier cost, not actual billing.
INPUT_USD_PER_MILLION = 0.30
OUTPUT_USD_PER_MILLION = 2.50


def add_poppler_to_path(env: dict[str, str]) -> None:
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


def find_usage(stderr: str) -> dict[str, Any] | None:
    prefix = "GEMINI_USAGE_JSON:"
    for line in stderr.splitlines():
        if line.startswith(prefix):
            try:
                payload = json.loads(line[len(prefix):])
                prompt = payload.get("prompt_tokens")
                output = payload.get("output_tokens")
                total = payload.get("total_tokens")
                if not isinstance(prompt, int) or not isinstance(output, int):
                    return payload
                cost = (prompt * INPUT_USD_PER_MILLION + output * OUTPUT_USD_PER_MILLION) / 1_000_000
                payload["estimated_paid_tier_cost_usd"] = round(cost, 8)
                payload["pricing_rates_usd_per_million"] = {
                    "input": INPUT_USD_PER_MILLION,
                    "output": OUTPUT_USD_PER_MILLION,
                }
                return payload
            except (ValueError, TypeError):
                return None
    return None


def main() -> int:
    for report_id in REPORT_IDS:
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
                f"eval/final already uses {manifest.get('model')!r}, not {MODEL!r}; "
                "do not mix models in one final run.",
                file=sys.stderr,
            )
            return 2
    else:
        manifest = {
            "model": MODEL,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "paid_tier_rates_usd_per_million_tokens": {
                "input": INPUT_USD_PER_MILLION,
                "output": OUTPUT_USD_PER_MILLION,
            },
            "pricing_source": "https://ai.google.dev/gemini-api/docs/pricing (checked 2026-10-27)",
            "reports": {},
        }

    env = os.environ.copy()
    env["GEMINI_API_KEY"] = key
    env["GEMINI_MODEL"] = MODEL
    add_poppler_to_path(env)
    print(f"Model: {MODEL}")
    print(f"Output folder: {RUN_DIR.relative_to(ROOT)}")
    print("Running a fresh final evaluation on the 8 labelled reports.")
    print("This makes up to 8 model calls. Paid-tier costs are estimated from returned token counts.\n")

    for report_id in REPORT_IDS:
        report = ROOT / "reports" / f"{report_id}.pdf"
        if not report.exists():
            report = ROOT / "reports" / f"{report_id}.jpg"
        output_path = RUN_DIR / f"{report_id}.json"
        previous = manifest.get("reports", {}).get(report_id, {})
        previous_usage = previous.get("usage") or {}
        if (
            previous.get("status") == "success"
            and output_path.exists()
            and isinstance(previous_usage.get("prompt_tokens"), int)
            and isinstance(previous_usage.get("output_tokens"), int)
            and isinstance(previous_usage.get("estimated_paid_tier_cost_usd"), (int, float))
        ):
            print(f"{report_id}: reusing saved result ({previous.get('latency_seconds', '?')}s)")
            continue
        print(f"Running {report_id} ({report.name})...", flush=True)
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, str(ROOT / "extract.py"), str(report)],
                capture_output=True, text=True, env=env, timeout=240, cwd=ROOT,
            )
            latency = time.perf_counter() - start
            usage = find_usage(completed.stderr or "")
            if completed.returncode != 0:
                error_text = (completed.stderr or completed.stdout or "Extractor failed without an error message.").strip()
                manifest["reports"][report_id] = {
                    "status": "error", "latency_seconds": round(latency, 3),
                    "error": error_text[:1200], "usage": usage,
                }
                write_json(manifest_path, manifest)
                print(f"  FAILED after {latency:.1f}s: {error_text[:300]}")
                continue
            prediction = json.loads(completed.stdout)
            if not isinstance(prediction, dict) or not isinstance(prediction.get("tests"), list):
                raise ValueError("Extractor stdout was not a JSON object with a tests array.")
            output_path = RUN_DIR / f"{report_id}.json"
            write_json(output_path, prediction)
            manifest["reports"][report_id] = {
                "status": "success",
                "latency_seconds": round(latency, 3),
                "report_file": str(report.relative_to(ROOT)),
                "output_file": str(output_path.relative_to(ROOT)),
                "extracted_rows": len(prediction["tests"]),
                "usage": usage,
            }
            write_json(manifest_path, manifest)
            cost = usage.get("estimated_paid_tier_cost_usd") if usage else None
            cost_text = f"; estimated paid-tier cost ${cost:.6f}" if isinstance(cost, (int, float)) else "; token usage not found"
            print(f"  OK: {len(prediction['tests'])} rows in {latency:.1f}s{cost_text}")
        except subprocess.TimeoutExpired:
            latency = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error", "latency_seconds": round(latency, 3),
                "error": "Extractor exceeded the 240-second evaluation timeout.",
            }
            write_json(manifest_path, manifest)
            print(f"  FAILED: timed out after {latency:.1f}s")
        except Exception as error:
            latency = time.perf_counter() - start
            manifest["reports"][report_id] = {
                "status": "error", "latency_seconds": round(latency, 3),
                "error": f"{type(error).__name__}: {error}",
            }
            write_json(manifest_path, manifest)
            print(f"  FAILED: {type(error).__name__}: {error}")

    successes = [r for r in REPORT_IDS if manifest.get("reports", {}).get(r, {}).get("status") == "success"]
    usage_rows = [(r, manifest["reports"][r].get("usage")) for r in successes]
    fully_metered = [(r, u) for r, u in usage_rows if u and isinstance(u.get("estimated_paid_tier_cost_usd"), (int, float))]
    if successes:
        total_latency = sum(manifest["reports"][r]["latency_seconds"] for r in successes)
        manifest["summary"] = {
            "successful_reports": len(successes),
            "expected_reports": len(REPORT_IDS),
            "mean_latency_seconds_successful": round(total_latency / len(successes), 3),
            "reports_with_token_usage": len(fully_metered),
            "estimated_paid_tier_cost_total_usd_for_metered_reports": round(
                sum(u["estimated_paid_tier_cost_usd"] for _, u in fully_metered), 8
            ),
            "estimated_paid_tier_cost_mean_usd_for_metered_reports": round(
                sum(u["estimated_paid_tier_cost_usd"] for _, u in fully_metered) / len(fully_metered), 8
            ) if fully_metered else None,
            "actual_billed_cost_note": "This is a paid-tier estimate from API-reported token counts, not an invoice. If these calls were served by the free tier, actual API usage cost is $0; verify the project's billing/usage dashboard.",
        }
    write_json(RUN_DIR / "summary.json", manifest.get("summary", {"successful_reports": len(successes), "expected_reports": len(REPORT_IDS)}))
    write_json(manifest_path, manifest)
    if len(successes) != len(REPORT_IDS):
        print("\nFinal run incomplete. Check eval/final/manifest.json, then rerun if appropriate.")
        return 2
    summary = manifest["summary"]
    print("\nFinal run complete")
    print(f"Mean latency: {summary['mean_latency_seconds_successful']:.2f}s/report")
    print(f"Reports with token counts: {summary['reports_with_token_usage']}/{len(REPORT_IDS)}")
    if summary["estimated_paid_tier_cost_mean_usd_for_metered_reports"] is not None:
        print(f"Estimated paid-tier cost per report (mean): ${summary['estimated_paid_tier_cost_mean_usd_for_metered_reports']:.6f}")
        print(f"Estimated paid-tier cost total: ${summary['estimated_paid_tier_cost_total_usd_for_metered_reports']:.6f}")
    else:
        print("Token usage wasn't found. Check extract.py's GEMINI_USAGE_JSON logging before reporting cost.")
    print("Run `py -3 score_eval.py eval/final` to calculate alias-aware accuracy metrics.")
    print("Actual billable spend depends on the project's free/paid tier; verify the billing dashboard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
