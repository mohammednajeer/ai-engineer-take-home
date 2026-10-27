
# Qualitative Review of Unlabelled Reports

## Method
The four reports without gold labels were reviewed manually by
comparing saved predictions with their source documents. No accuracy
score is calculated because there are no reference JSON labels.

Model: gemini-3.5-flash-lite
Reports reviewed: 4
Successful extraction runs: 4/4
Mean latency: 3.01 seconds per report

## Findings

### report_04.pdf
- Extracted 9 rows.
- Test names, values, units, and reference ranges were consistent
  with the source in the manual review.
- No clear extraction errors were identified.

### report_07.pdf
- Extracted 10 rows.
- Serum Globulin appears to be 3.1 g/dL in the source, but the
  prediction is 3.3 g/dL. The printed value is partly obscured by
  a circle, so this is recorded as a likely extraction error.
- The handwritten follow-up note was not extracted as a test result.

### report_10.jpg
- Extracted 9 rows.
- Numerical results were consistent with the source in the manual
  review.
- T4 and TSH unit strings contain malformed characters:
  `Âµg/dL` and `ÂµIU/mL`, instead of `µg/dL` and `µIU/mL`.
- The source labels TSH as `TSH (Ultrasensitive)`; the prediction
  shortens this to `TSH`.

### report_12.jpg
- Extracted 0 rows.
- The source is a prescription containing medicines and requested
  investigations, not measured laboratory results.
- An empty `tests` array is appropriate for this extractor.

## Limitations
This is a qualitative spot-check, not a statistical accuracy
estimate. The four reports do not have gold labels, and some
visual details require human interpretation. These findings are
not included in the labelled evaluation metrics.
