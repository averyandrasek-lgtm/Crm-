# Champion Alert

## Purpose
Watch champion and decision-maker contacts (`role_category: champion` or
`decision_maker`, and everyone in `champions.csv`) for high-risk signals —
departure, company change, or role change — and alert a human fast. Per
`config/pipeline.yaml` `champion.alert_window_hours`, this is a
time-sensitive path distinct from the routine refresh cadence.

## Inputs
- `champions.csv`
- `state/contacts.jsonl` (filtered to `role_category` in
  `champion`/`decision_maker`, or `open_deal_ids` non-empty)
- `state/detections.jsonl`
- `config/pipeline.yaml` (`champion.alert_window_hours`,
  `champion.cadence_steps`, `champion.cadence_days`)

## Instructions
1. Any detection of type `contact_departure`, `job_change`, or a
   role/title change on a champion or decision-maker is high_risk by
   definition (per `CLAUDE.md` section 4) — it always requires approval,
   regardless of confidence tier, as long as confidence is not `low`.
2. Such a detection must produce an alert file in `output/alerts/` within
   `champion.alert_window_hours` of detection — do not let it sit in the
   routine refresh queue.
3. The alert must state: who the contact is, what changed, the quoted
   evidence, which open deals (if any) are affected, and the recommended
   next action (e.g. "reassign champion", "flag deal at risk").
4. On the champion cadence (`champion.cadence_steps` touches over
   `champion.cadence_days` days), also alert if a champion has *not* been
   re-verified — silence is itself a signal worth surfacing, but must be
   labeled as "no new evidence" rather than implying a detection.
5. Never mark a champion alert as resolved automatically. Resolution
   requires a human decision recorded via `scripts/update_contact.py`
   with an explicit `source_detection_id`.

## Output format
A markdown alert file at `output/alerts/[date]-[contact_id]-champion.md`
with the fields listed above.
