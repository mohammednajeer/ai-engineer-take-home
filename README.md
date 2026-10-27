# Lab report extraction: starter kit

Read the brief first. This file only covers what's in the kit and how to run it.

## Contents

- `extract.py`: the baseline extractor.
- `reports/`: 12 sample documents (`.pdf` and `.jpg`).
- `gold/`: labels for 8 of the 12, named after the report they belong to.
- `schema.json`: the output shape.

## Run it

Use Python 3.10 or newer and install Poppler, which provides `pdftoppm`:

- macOS: `brew install poppler`
- Ubuntu/Debian: `sudo apt-get install poppler-utils`

The supplied Gemini setup is one starting point. You can use free credits or adapt the starter to an accessible provider or a local open model; paid access is not required. If you change the model/provider to get started, measure the baseline with that setup before changing its extraction behavior, and document the substitution.

There are no Python package dependencies for the supplied setup. From this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pdftoppm -v
python -c 'import getpass, os, subprocess, sys; env = os.environ.copy(); env["GEMINI_API_KEY"] = getpass.getpass("Gemini API key: "); sys.exit(subprocess.call([sys.executable, "extract.py", "reports/report_01.pdf"], env=env))'
```

The last command securely prompts for your key and runs one extraction as a setup smoke test. It makes an API call, which may incur charges depending on your account, and should print JSON containing a `tests` array. It does not save the key or put it in shell history. For repeated calls, set `GEMINI_API_KEY` through your usual local secret/environment setup; do not commit it.

The default model is `gemini-3.8-flash`. Google's [pricing page](https://ai.google.dev/gemini-api/docs/pricing) currently lists free-tier input and output for this model (checked 8 October 2026). You can start with a free-tier project and an API key from [Google AI Studio](https://aistudio.google.com/apikey). Check your project's [active rate limits](https://ai.google.dev/gemini-api/docs/rate-limits): quotas apply per project, and access and limits may change. A key on a paid project can incur charges. If access or quota is insufficient, use another model or provider and document your setup.

The baseline calls the Gemini REST API. You're free to change model (`GEMINI_MODEL`) or provider; record the exact choice with your measurements. Whatever you change, this must keep working and keep printing schema-valid JSON to stdout, because it's how we'll run your version on reports you haven't seen:

```bash
python extract.py <path-to-report>
```

If your version needs different setup (other packages, other environment variables), say so at the top of your README.

For setup errors: a missing `pdftoppm` means Poppler is not on `PATH`; HTTP 401/403 means check key/project access, 404 means check model availability, and 429 means check quota. For a connection/TLS error, check network access before retrying. Never disable TLS verification. Keep access troubleshooting within the timebox; document constraints and any alternative you use.
