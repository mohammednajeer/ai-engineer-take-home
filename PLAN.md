
# Investigation Plan

## Objective
Improve the supplied lab-report extractor through measurable,
reproducible evaluation while preserving its command-line interface.

## Approach
1. Inspect the extractor, schema, 12 reports, and 8 gold labels.
2. Define evaluation metrics for test names, values, units,
   reference ranges, missing results, and extra results.
3. Run the unchanged extractor on labelled reports and record
   baseline accuracy, latency, and cost.
4. Investigate mismatches and identify the three most important
   failure categories using actual examples.
5. Test targeted improvements one at a time and compare results
   against the baseline using the same evaluation.
6. Record at least one unsuccessful experiment and explain
   its results.
7. Verify JSON/schema compliance and the required command.
   Document findings, prompts, decisions, and limitations.

## Constraints
Preserve the required extract.py entry point and Git history.
Avoid hardcoded fixes for individual reports. Protect API credentials
and stay within the 4–6 hour time budget.
