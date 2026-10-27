"""Extract structured lab results from a lab report.

Usage:
    python extract.py reports/report_01.pdf

Prints JSON matching schema.json to stdout.
"""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
DPI = 60

PROMPT = """You are an expert at reading medical lab reports.

Look at this lab report and extract every test result from it.

Return JSON in exactly this format:
{"tests": [{"test_name": "...", "value": 0.0, "unit": "...", "reference_range": "...", "status": "normal"}]}

Rules:
- Use the standard medical name for each test.
- value must be a number.
- If a reference range is missing from the report, fill in the standard reference range for that test.
- status is "normal", "high" or "low", based on the value and the reference range.
- Be thorough. Do not miss any tests.
"""

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}



def load_images(path: Path) -> list[tuple[str, str]]:
    """Return every report page as (media_type, base64 data)."""
    if path.suffix.lower() == ".pdf":
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "page"
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-r", str(DPI),
                        "-png",
                        str(path),
                        str(prefix),
                    ],
                    check=True,
                    capture_output=True,
                )
            except FileNotFoundError:
                raise RuntimeError( "Install Poppler (pdftoppm); see README.md.") from None

            pages = sorted( Path(directory).glob("page-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]), )

            if not pages:
                raise RuntimeError( f"No pages could be rendered from {path}.")

            return [
                ("image/png",base64.standard_b64encode(page.read_bytes()).decode(),)
                for page in pages
            ]

    suffix = path.suffix.lower()
    if suffix not in MEDIA_TYPES:
        raise RuntimeError(
            f"Unsupported report format: {path.suffix}"
        )

    return [
        (
            MEDIA_TYPES[suffix],
            base64.standard_b64encode(path.read_bytes()).decode(),
        )
    ]



def call_model(images: list[tuple[str, str]]) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "Set GEMINI_API_KEY; see README.md. No API call made."
        )

    parts = [
        {
            "inlineData": {
                "mimeType": media_type,
                "data": data,
            }
        }
        for media_type, data in images
    ]
    parts.append({"text": PROMPT})

    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 16000,
        },
    }

    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(),
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"Gemini HTTP {error.code}; check API access, model and quota. See README.md."
        ) from None
    except urllib.error.URLError:
        raise RuntimeError(
            "Gemini connection failed; check network/TLS access and retry. See README.md."
        ) from None

    candidate = result.get("candidates", [{}])[0]
    return "".join(
        part["text"]
        for part in candidate.get("content", {}).get("parts", [])
        if "text" in part and not part.get("thought")
    )


def parse(text: str) -> list[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(match.group(0))["tests"]
    except Exception:
        return []


def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean(tests: list[dict]) -> list[dict]:
    out = []
    for t in tests:
        out.append({
            "test_name": str(t.get("test_name", "")).strip(),
            "value": to_number(t.get("value")),
            "unit": t.get("unit") or None,
            "reference_range": t.get("reference_range") or None,
            "status": t.get("status"),
        })
    return out


def extract(path: Path) -> dict:
    images = load_images(path)
    return {"tests": clean(parse(call_model(images)))}

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))
    except RuntimeError as error:
        sys.exit(str(error))
