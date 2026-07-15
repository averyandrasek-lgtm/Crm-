# Presend Check

## Purpose
Before any outbound send to a contact (email, sequence step, campaign),
check whether the record is stale or risky enough that sending would be
a mistake — a bounce, a wrong title in the personalization, or a contact
who has departed.

## Inputs
- The specific `contact_id` about to be sent to.
- `state/contacts.jsonl`
- `config/pipeline.yaml` (`presend.decay_score_threshold`,
  `presend.days_since_verify_threshold`,
  `presend.bounced_lookback_days`)

## Instructions
1. Block the send and flag for review if any of the following hold:
   - `decay_score` >= `presend.decay_score_threshold`.
   - `last_verified_at` is null, or older than
     `presend.days_since_verify_threshold` days.
   - `bounce_history` contains an entry within
     `presend.bounced_lookback_days` days.
   - There is a `pending_review` or `approved` (not yet `applied`)
     detection of type `contact_departure` or `job_change` for this
     contact.
2. If none of the above hold, clear the contact to send.
3. If blocked, write the reason (with the specific threshold crossed and
   the actual value) to `output/alerts/` rather than silently dropping
   the send — a blocked send still needs a human to decide what to do
   next (skip, refresh first, or send anyway).
4. Never clear a send based on an assumption that a contact "is probably
   still there" — absence of a departure signal is not verification.

## Output format
A pass/block decision plus, if blocked, a short markdown note in
`output/alerts/` naming the contact, the threshold crossed, and the
actual value observed.
