#!/usr/bin/env python3
"""Apply a single approved field change to a contact in state/contacts.jsonl.

This is the ONLY way the agent is permitted to mutate contact state in
memory (see CLAUDE.md section 3) -- nothing else should append or rewrite
state/contacts.jsonl directly.

CLI: contact_id, field, new_value, source_detection_id.

The script loads the contact, confirms the field exists in
schemas/contact.schema.json, loads the source detection from
state/detections.jsonl, and confirms the change is allowed:

- The detection must belong to the same contact_id and must propose this
  exact field/value.
- The detection's confidence must not be "low".
- If the field's risk category requires approval (config/pipeline.yaml
  approval_required), the detection's status must already be "approved"
  (or "applied").

On success the contact record is updated, updated_at is bumped, the
result is re-validated against the schema, and the full contacts.jsonl is
rewritten.

Run as:
  python3 scripts/update_contact.py <contact_id> <field> <new_value> <source_detection_id>
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
SCHEMA_DIR = BASE_DIR / "schemas"
CONFIG_DIR = BASE_DIR / "config"

CONTACTS_PATH = STATE_DIR / "contacts.jsonl"
DETECTIONS_PATH = STATE_DIR / "detections.jsonl"
CONTACT_SCHEMA_PATH = SCHEMA_DIR / "contact.schema.json"
PIPELINE_CONFIG_PATH = CONFIG_DIR / "pipeline.yaml"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path: Path) -> list:
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def write_jsonl(path: Path, records: list) -> None:
    with open(path, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


class UpdateRejected(Exception):
    pass


def find_detection(detections: list, detection_id: str) -> dict:
    for detection in detections:
        if detection.get("detection_id") == detection_id:
            return detection
    raise UpdateRejected(f"source_detection_id '{detection_id}' not found in detections.jsonl")


def validate_change_allowed(
    contact: dict,
    field: str,
    new_value,
    detection: dict,
    contact_schema: dict,
    pipeline_config: dict,
) -> None:
    if field not in contact_schema.get("properties", {}):
        raise UpdateRejected(f"field '{field}' is not defined in contact.schema.json")

    if detection.get("contact_id") != contact["contact_id"]:
        raise UpdateRejected(
            f"detection {detection.get('detection_id')} belongs to contact "
            f"'{detection.get('contact_id')}', not '{contact['contact_id']}'"
        )

    proposed_changes = detection.get("proposed_changes", {})
    if field not in proposed_changes:
        raise UpdateRejected(f"detection does not propose a change to field '{field}'")

    if proposed_changes[field] != new_value:
        raise UpdateRejected(
            f"new_value '{new_value}' does not match detection's proposed_changes "
            f"['{field}'] = '{proposed_changes[field]}'"
        )

    if detection.get("confidence") == "low":
        raise UpdateRejected("detection confidence is 'low'; low-confidence detections are never acted on")

    risk_category = detection.get("field_risk_category")
    approval_required = pipeline_config.get("approval_required", {}).get(risk_category, True)

    if approval_required and detection.get("status") not in ("approved", "applied"):
        raise UpdateRejected(
            f"field_risk_category '{risk_category}' requires approval; "
            f"detection status is '{detection.get('status')}', expected 'approved' or 'applied'"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contact_id")
    parser.add_argument("field")
    parser.add_argument("new_value")
    parser.add_argument("source_detection_id")
    args = parser.parse_args()

    contacts = load_jsonl(CONTACTS_PATH)
    detections = load_jsonl(DETECTIONS_PATH)
    contact_schema = load_json(CONTACT_SCHEMA_PATH)
    pipeline_config = load_yaml(PIPELINE_CONFIG_PATH)

    contact_index = next(
        (i for i, c in enumerate(contacts) if c.get("contact_id") == args.contact_id), None
    )
    if contact_index is None:
        print(f"ERROR: contact_id '{args.contact_id}' not found", file=sys.stderr)
        return 1

    contact = contacts[contact_index]

    try:
        detection = find_detection(detections, args.source_detection_id)
        validate_change_allowed(
            contact, args.field, args.new_value, detection, contact_schema, pipeline_config
        )
    except UpdateRejected as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1

    old_value = contact.get(args.field)
    contact[args.field] = args.new_value
    contact["updated_at"] = now_iso()

    try:
        jsonschema.validate(instance=contact, schema=contact_schema)
    except jsonschema.ValidationError as exc:
        print(f"REJECTED: updated contact fails schema validation: {exc.message}", file=sys.stderr)
        return 1

    contacts[contact_index] = contact
    write_jsonl(CONTACTS_PATH, contacts)

    print(
        f"OK: {args.contact_id}.{args.field} '{old_value}' -> '{args.new_value}' "
        f"(detection {args.source_detection_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
