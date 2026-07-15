# Candidate Scanner

## Purpose
Scan available sources (CRM export, LinkedIn, company websites, email
signatures, news) for contacts in `state/contacts.jsonl` whose data may be
stale, and produce a list of candidates for further investigation. This
prompt does not produce detections itself — it narrows the full contact
list down to the ones worth checking.

## Inputs
- `state/contacts.jsonl` — current contact records.
- `champions.csv` — contacts on the champion cadence (check these first,
  per `config/pipeline.yaml` champion.cadence_days).
- Any connected sources (HubSpot/Salesforce MCP, Gmail, Apollo, Clay) if
  available.

## Instructions
1. For each contact, compute staleness from `last_verified_at` and
   `decay_score`. Prioritize:
   - Champions and decision-makers first.
   - Contacts linked to open deals (`open_deal_ids` non-empty).
   - Contacts not verified in `presend.days_since_verify_threshold` days
     (see `config/pipeline.yaml`).
2. For each prioritized contact, check available sources for signals:
   job changes, title changes, company closures, bounced emails, or
   departure signals (e.g. auto-reply, LinkedIn "no longer at X").
3. Do not fabricate signals. If no source is reachable for a contact,
   say so explicitly rather than guessing.
4. Output a candidate list: `contact_id`, reason for flagging, and the
   raw source snippet that triggered the flag. This becomes the input to
   `prompts/detection_validator.md`.
5. If an MCP connector needed for a source is unavailable, note it and
   continue with the sources that are available. Never silently skip a
   contact without recording why.

## Output format
A markdown or JSON list of candidates, each with:
- `contact_id`
- `flag_reason`
- `raw_source_snippet` (must be a real quote/URL, not a paraphrase)
