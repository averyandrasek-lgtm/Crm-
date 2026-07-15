# Refresh Planner

## Purpose
Given the set of validated, actionable detections in
`state/detections.jsonl` (status `pending_review` or `approved`), plan the
concrete sequence of updates: which go through automatically (low_risk),
which need human approval (medium/high_risk), and in what order.

## Inputs
- `state/detections.jsonl`
- `state/contacts.jsonl`
- `config/pipeline.yaml`

## Instructions
1. Group pending detections by `contact_id` and `field_risk_category`.
2. For `low_risk` detections where `approval_required.low_risk` is
   `false`: queue them for immediate application via
   `scripts/update_contact.py` followed by `scripts/write_to_crm.py`.
   Still write the audit entry — automatic does not mean unlogged.
3. For `medium_risk` and `high_risk` detections: prepare a review packet
   (contact, current value, proposed value, evidence, confidence) and
   write it to `output/alerts/` for human approval rather than applying
   it.
4. Never batch a high_risk change with an unrelated low_risk change in a
   way that implies one approval covers both.
5. If a contact has multiple pending detections that conflict (e.g. two
   different proposed titles), flag the conflict explicitly instead of
   picking one silently.
6. Order the plan so that a contact's `company` change is applied before
   any dependent `title` or `email domain` corrections built on the new
   company.

## Output format
A per-contact plan listing: detections to auto-apply, detections
awaiting approval, and any conflicts requiring a human decision before
either can proceed.
