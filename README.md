# mera.health AI Engineer take-home — lab-report extraction

## Run

Requires Python 3.10+ and Poppler (`pdftoppm`) on `PATH`; no third-party Python packages are needed. Set `GEMINI_API_KEY` securely. Default model is `gemini-3.5-flash-lite` (`GEMINI_MODEL` can override it). Never commit keys.

```powershell
py -3 extract.py reports/report_01.pdf
```

Required CLI remains `python extract.py <path>` and prints a JSON object with a `tests` array. The evaluation runners prompt for the API key without echoing it; API usage may incur charges depending on project tier.

## Evaluation and results

Eight labelled reports contain 138 gold rows. `score_eval.py` is the common alias-aware scorer: it normalizes case/punctuation and selected name variants; numeric values use 0.01 absolute tolerance; units are case-insensitive; reference ranges ignore whitespace and normalize dash characters. A row is exact only when name, value, unit, and range match. Results are against supplied labels, not clinical accuracy; labels were not edited.

| Metric | Original | Final |
|---|---:|---:|
| Exact rows / gold rows | 100/138 | 131/138 |
| Exact-row recall | 72.5% | 94.9% (+22.4 pp) |
| Name precision / recall | 99.1% / 81.9% | 97.8% / 97.8% |
| Value accuracy on name-matched rows | 92.0% | 99.3% |
| Unit accuracy on name-matched rows | 100% | 100% |
| Reference-range accuracy on name-matched rows | 92.9% | 97.8% |
| Mean latency/report | 5.60 s | 9.36 s |
| Estimated paid-tier cost/report | $0.002355 | $0.002762 |

Estimated cost rose 17.3%; latency rose 67% (latency varies with API load). Costs use API-reported tokens and Standard rates of $0.30/1M input and $2.50/1M output tokens ([official pricing](https://ai.google.dev/gemini-api/docs/pricing), checked 2026-10-27). Eight-report totals: $0.018841 baseline and $0.022097 final. These are estimates, not an invoice; eligible free-tier use may cost $0. At 10,000 reports/day, final cost projects to ~$27.62/day or ~$828.60 per 30-day month before retries/infrastructure.

Reproduce (evaluation makes API calls; scoring does not):

```powershell
py -3 baseline_eval.py
py -3 score_eval.py eval/baseline
py -3 final_eval.py
py -3 score_eval.py eval/final
```

Results/manifests are saved under `eval/`. `baseline_cost_eval.py` replays original source commit `c3786d9` for cost only. The audit found a likely label error: `report_01` platelet count is 304000 in gold but 340000 in the PDF and extraction; the gold label was left unchanged.

## Three failure categories and fixes

1. **PDF pages omitted:** baseline `pdftoppm -f 1 -l 1 -singlefile` rendered only page one. `load_images` now renders all pages. `report_11` rose from 30 to 54 extracted rows; final scoring matched 54/54 labelled rows.
2. **Text values became null:** baseline `to_number()` discarded `Dark Yellow`, `Clear`, `Negative`, `Present (+)`, `2-3`, and `< 0.5`. Cleaning now preserves numeric values as numbers and other reported values as strings. On `report_06`, exact rows rose from 2/12 after multi-page processing to 6/12 after value preservation.
3. **Reference ranges invented:** baseline prompt requested a standard range when missing. It now says to copy the printed range or return `null`; never infer or copy a range. In `report_03`, exact rows improved from 5/8 to 8/8 in the reference-guard run.

## Experiments and unlabelled reports

- **120 DPI not adopted:** on `report_06` and `report_11`, exact rows changed from 60/66 to 61/66 while mean latency rose from 7.31 s to 9.09 s (+24.4%). One extra row in two reports did not justify the latency cost.
- **Extra completeness instruction not adopted:** same two-report sample changed from 60/66 to 61/66; `report_06` improved 6/12 to 7/12 while `report_11` stayed 54/54. Evidence was too limited to justify extra prompt complexity.
- **Unlabelled qualitative review (not scored):** `report_04` had 9 plausible rows. `report_07` likely misread Serum Globulin (source appears 3.1 g/dL; output 3.3). `report_10` had malformed micro-symbols in one saved run, though a later smoke test showed `µ` correctly. `report_12` is a prescription with no measured results, so `tests: []` is appropriate. Review mean latency was 3.01 s/report; see `eval/unlabelled_review/manual_review.md`.

## Prompt, design questions, decision log

The final prompt is preserved in [`PROMPT.md`](PROMPT.md) and in `extract.py`. It is deliberately source-faithful: preserve textual/inequality values, copy printed ranges, and use `null` if a range is absent rather than guessing.

**RAG?** Not for core extraction: retrieval cannot recover pixels/text absent from the report and could introduce external ranges that conflict with the source. A separate, labelled enrichment stage could be considered later.

**Fine-tuning?** Not with eight labels and known label issues. First collect a larger, corrected dataset with held-out labs/layouts, then compare tuning with prompt/pipeline fixes.

**Multi-step agent?** Not yet. All-page rendering and value-preserving cleaning fix known root causes. Agent loops add latency, cost, and duplicate/inconsistent output; the two-report completeness test added just one exact row and did not change `report_11`.

**Decision log:** switched from `gemini-3.8-flash` after repeated 503/timeouts; verified `gemini-3.5-flash-lite` via text/PDF smoke tests and used it for both scored versions. Left gold labels unchanged after manually checking the platelet discrepancy. Rejected 120 DPI and the extra completeness instruction because gains were too small for their latency/complexity. Manually reviewed source reports, kept separate baseline/final/experiment outputs, preserved Git history, and retained the CLI.
