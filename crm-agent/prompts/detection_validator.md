# Detection Validator

## Purpose
Turn a raw candidate flag (from `prompts/candidate_scanner.md`) into a
validated detection object that conforms to
`schemas/detection.schema.json`, or reject it.

## Inputs
- Candidate list from the scanner.
- `schemas/detection.schema.json`.
- `config/pipeline.yaml` (`detection_thresholds`, field risk mapping in
  `CLAUDE.md` section 4).

## Instructions
1. For each candidate, gather evidence. Evidence entries require
   `source`, `date`, and a `quote` — a real quoted line, not a summary.
   A URL is required whenever the source is a web page.
2. Count independent evidence sources. If fewer than
   `detection_thresholds.min_evidence_sources`, confidence cannot be
   `high`.
3. Assign `confidence`:
   - `high`: multiple independent, dated, quoted sources agree.
   - `medium`: one solid source, or multiple weakly-corroborating
     sources.
   - `low`: single weak or ambiguous signal.
4. Map the proposed change to a `field_risk_category` per `CLAUDE.md`
   section 4 (low_risk / medium_risk / high_risk).
5. Set `requires_approval` from `config/pipeline.yaml`
   `approval_required` for that risk category.
6. If confidence is `low`, set `status: rejected` and do not propose it
   for action — log it and stop. Per `CLAUDE.md` section 3, low-confidence
   detections are never acted on.
7. If confidence meets `detection_thresholds.min_confidence_to_act`,
   set `status: pending_review` and write the object to
   `state/detections.jsonl` (via the same validation path used by
   `scripts/validate_state.py` — never hand-append unvalidated JSON).
8. Never invent a `quote` or `url`. If evidence can't be quoted verbatim,
   the detection cannot reach `high` confidence.

## Output format
One JSON object per `schemas/detection.schema.json`, or an explicit
rejection note with reason.
