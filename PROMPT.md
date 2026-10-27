# Final extraction prompt

This is the final extraction prompt used in `extract.py`. It asks the model to return each row faithfully, preserve qualitative values and inequalities, and avoid inventing missing reference ranges.

```text
You are an expert at reading medical lab reports.

Look at this lab report and extract every test result from it.

Return JSON in exactly this format:
{"tests": [{"test_name": "...", "value": 0.0, "unit": "...", "reference_range": "...", "status": "normal"}]}

Rules:
- Use the standard medical name for each test.
- Preserve the reported value accurately. Use a number for a single numeric result. Use a string for qualitative results such as "Dark Yellow" or "Negative", inequalities such as "< 0.5", and ranges such as "2-3". Use null only when no result is reported. Do not invent or calculate a replacement value.
- Copy each reference range exactly as printed in the report, including units and inequality signs when present.
- If a reference range is not printed for a test, return null for reference_range.
- Never invent, infer, calculate, look up, or fill in a standard reference range.
- Never copy a reference range from another test.
- status is "normal", "high" or "low", based on the value and the reference range.
- Be thorough. Do not miss any tests.
```

The rules are shaped to prioritize source fidelity: a missing range stays missing instead of being replaced with a plausible but unsupported standard value. Preprocessing renders every PDF page and sends the images in one model request.

## Experimental prompt addition (tested, not adopted)

The completeness experiment appended this exact instruction to the final prompt for `report_06.pdf` and `report_11.pdf` only:

```text
Experimental completeness-check instruction:
After drafting the JSON, scan every provided page once more specifically for test rows not yet included. Add only test results visibly present in the report. Do not duplicate rows, infer missing results, or guess fields.
```

Why it was tested: hypothesized that a second completeness-focused scan could recover omitted rows. It was not adopted as a default because the two-report test changed exact rows from 60/66 to 61/66 and did not change `report_11`; the sample was too small to justify the extra complexity.
