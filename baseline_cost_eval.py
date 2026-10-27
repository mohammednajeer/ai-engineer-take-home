"""Meter a baseline-cost replay from the original extractor commit.

Run from the project root:
    py -3 baseline_cost_eval.py

This does NOT alter eval/baseline/ or its original predictions. It retrieves
extract.py from the initial starter commit, adds stderr-only usage logging, and
uses the same model/rates as final_eval.py for a separate cost-only replay.
"""
from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
BASELINE_COMMIT = os.environ.get("BASELINE_GIT_COMMIT", "c3786d9")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
RUN_DIR = ROOT / "eval" / "baseline_cost_replay"
INPUT_USD_PER_MILLION = 0.30
OUTPUT_USD_PER_MILLION = 2.50
REPORT_IDS = [
    "report_01", "report_02", "report_03", "report_05",
    "report_06", "report_08", "report_09", "report_11",
]
USAGE_PREFIX = "GEMINI_USAGE_JSON:"


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


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_baseline_source() -> str:
    result = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:extract.py"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read {BASELINE_COMMIT}:extract.py from Git history. "
            "Check that commit c3786d9 exists locally, or set BASELINE_GIT_COMMIT.\n"
            + result.stderr.strip()
        )
    source = result.stdout
    needle = "            result = json.load(response)\n"
    if needle not in source:
        raise RuntimeError("Could not find baseline response line to instrument; no API calls made.")
    logger = '''            result = json.load(response)
            usage = result.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount")
            total_tokens = usage.get("totalTokenCount")
            if isinstance(prompt_tokens, int) and isinstance(total_tokens, int):
                print(
                    "GEMINI_USAGE_JSON:" + json.dumps({
                        "prompt_tokens": prompt_tokens,
                        "output_tokens": max(0, total_tokens - prompt_tokens),
                        "total_tokens": total_tokens,
                    }),
                    file=sys.stderr,
                    flush=True,
                )
'''
    source = source.replace(needle, logger, 1)
    # Baseline JSON remains semantically identical; escaping Unicode makes its stdout
    # safely capturable on Windows consoles configured for cp1252.
    source = source.replace("ensure_ascii=False", "ensure_ascii=True")
    return source


def parse_usage(stderr: str) -> dict[str, Any] | None:
    for line in stderr.splitlines():
        if not line.startswith(USAGE_PREFIX):
            continue
        try:
            data = json.loads(line[len(USAGE_PREFIX):])
            prompt = data.get("prompt_tokens")
            output = data.get("output_tokens")
            if not isinstance(prompt, int) or not isinstance(output, int):
                return None
            data["estimated_paid_tier_cost_usd"] = round(
                (prompt * INPUT_USD_PER_MILLION + output * OUTPUT_USD_PER_MILLION) / 1_000_000,
                8,
            )
            data["pricing_rates_usd_per_million"] = {
                "input": INPUT_USD_PER_MILLION,
                "output": OUTPUT_USD_PER_MILLION,
            }
            return data
        except (ValueError, TypeError):
            return None
    return None


def main() -> int:
    try:
        source = get_baseline_source()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2

    for report_id in REPORT_IDS:
        report = ROOT / "reports" / f"{report_id}.pdf"
        if not report.exists():
            report = ROOT / "reports" / f"{report_id}.jpg"
        if not report.exists():
            print(f"Missing source report: {report_id}", file=sys.stderr)
            return 2

    key = getpass.getpass("Gemini API key (hidden): ").strip()
    if not key:
        print("No API key entered; stopping without API calls.", file=sys.stderr)
        return 2

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RUN_DIR / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("model") != MODEL or manifest.get("baseline_commit") != BASELINE_COMMIT:
            print("Existing replay uses a different model or baseline commit; use a fresh output folder.", file=sys.stderr)
            return 2
    else:
        manifest = {
            "model": MODEL,
            "baseline_commit": BASELINE_COMMIT,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": "Cost-only replay of original extractor; accuracy scores remain from eval/baseline.",
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
    print(f"Baseline source commit: {BASELINE_COMMIT}")
    print(f"Model: {MODEL}")
    print(f"Output folder: {RUN_DIR.relative_to(ROOT)}")
    print("This is a separate, cost-only replay; it does not overwrite baseline predictions or metrics.")
    print("It may make up to 8 API calls. Check your quota first.\n")

    with tempfile.TemporaryDirectory(prefix="baseline_metered_") as temp_dir:
        temp_script = Path(temp_dir) / "extract_baseline_metered.py"
        temp_script.write_text(source, encoding="utf-8")
        for report_id in REPORT_IDS:
            old = manifest["reports"].get(report_id, {})
            if old.get("status") == "success" and old.get("usage", {}).get("estimated_paid_tier_cost_usd") is not None:
                print(f"{report_id}: reusing saved metering ({old.get('latency_seconds')}s)")
                continue
            report = ROOT / "reports" / f"{report_id}.pdf"
            if not report.exists():
                report = ROOT / "reports" / f"{report_id}.jpg"
            print(f"Metering baseline {report_id}...", flush=True)
            start = time.perf_counter()
            try:
                completed = subprocess.run(
                    [sys.executable, str(temp_script), str(report)],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=240,
                )
                latency = round(time.perf_counter() - start, 3)
                usage = parse_usage(completed.stderr or "")
                if completed.returncode != 0:
                    manifest["reports"][report_id] = {
                        "status": "error", "latency_seconds": latency,
                        "usage": usage,
                        "error": (completed.stderr or completed.stdout or "Extractor failed").strip()[-1600:],
                    }
                    write_json(manifest_path, manifest)
                    print(f"  FAILED after {latency:.1f}s; see manifest.json")
                    continue
                prediction = json.loads(completed.stdout)
                if not isinstance(prediction, dict) or not isinstance(prediction.get("tests"), list):
                    raise ValueError("Baseline output was not a JSON object with a tests array")
                write_json(RUN_DIR / f"{report_id}.json", prediction)
                manifest["reports"][report_id] = {
                    "status": "success", "latency_seconds": latency,
                    "extracted_rows": len(prediction["tests"]), "usage": usage,
                }
                write_json(manifest_path, manifest)
                cost = usage.get("estimated_paid_tier_cost_usd") if usage else None
                print(f"  OK: {len(prediction['tests'])} rows in {latency:.1f}s; " +
                      (f"estimated paid-tier cost ${cost:.6f}" if cost is not None else "token usage unavailable"))
            except Exception as error:
                manifest["reports"][report_id] = {
                    "status": "error", "error": f"{type(error).__name__}: {error}",
                    "latency_seconds": round(time.perf_counter() - start, 3),
                }
                write_json(manifest_path, manifest)
                print(f"  FAILED: {type(error).__name__}: {error}")

    metered = [
        (report_id, manifest["reports"].get(report_id, {}).get("usage"))
        for report_id in REPORT_IDS
        if manifest["reports"].get(report_id, {}).get("status") == "success"
    ]
    metered = [(report_id, usage) for report_id, usage in metered
               if usage and isinstance(usage.get("estimated_paid_tier_cost_usd"), (int, float))]
    summary = {
        "successful_reports": sum(manifest["reports"].get(r, {}).get("status") == "success" for r in REPORT_IDS),
        "expected_reports": len(REPORT_IDS),
        "reports_with_token_counts": len(metered),
        "estimated_paid_tier_cost_total_usd": round(sum(u["estimated_paid_tier_cost_usd"] for _, u in metered), 8),
        "estimated_paid_tier_cost_mean_usd": round(sum(u["estimated_paid_tier_cost_usd"] for _, u in metered) / len(metered), 8) if metered else None,
        "note": "Cost-only replay: token-based paid-tier estimate from a fresh baseline run. Initial baseline latency and accuracy remain reported from eval/baseline.",
    }
    manifest["summary"] = summary
    write_json(manifest_path, manifest)
    print("\nBaseline cost replay summary")
    print(f"Successful reports: {summary['successful_reports']}/{summary['expected_reports']}")
    print(f"Reports with token counts: {summary['reports_with_token_counts']}/{summary['expected_reports']}")
    if summary["estimated_paid_tier_cost_mean_usd"] is not None:
        print(f"Estimated paid-tier cost per report: ${summary['estimated_paid_tier_cost_mean_usd']:.6f}")
        print(f"Estimated paid-tier total: ${summary['estimated_paid_tier_cost_total_usd']:.6f}")
    print(f"Saved metering details under {RUN_DIR.relative_to(ROOT)}; no baseline prediction or gold file was overwritten.")
    return 0 if summary["successful_reports"] == len(REPORT_IDS) and summary["reports_with_token_counts"] == len(REPORT_IDS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
