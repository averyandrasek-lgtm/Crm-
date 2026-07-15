#!/usr/bin/env python3
"""Validate the integrity of state/*.jsonl.

Loads state/contacts.jsonl, state/detections.jsonl, and state/audit.jsonl,
validates every line against its JSON Schema, and checks referential
integrity across the three files:

- Every detection.contact_id and audit.contact_id must exist in
  contacts.jsonl.
- Every audit entry must have a matching detection_id whose status is
  "approved" or "applied".

Exits 0 if all checks pass, 1 if any check fails (errors are printed to
stderr).

Run as: python3 scripts/validate_state.py
"""

import json
import sys
from pathlib import Path

import jsonschema

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
SCHEMA_DIR = BASE_DIR / "schemas"

CONTACTS_PATH = STATE_DIR / "contacts.jsonl"
DETECTIONS_PATH = STATE_DIR / "detections.jsonl"
AUDIT_PATH = STATE_DIR / "audit.jsonl"


def load_jsonl(path: Path) -> list:
    records = []
    if not path.exists():
        return records
    with open(path) as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{lineno}: invalid JSON ({exc})")
    return records


def load_schema(name: str) -> dict:
    with open(SCHEMA_DIR / name) as f:
        return json.load(f)


def validate_records(records: list, schema: dict, label: str, errors: list) -> None:
    for i, record in enumerate(records, start=1):
        try:
            jsonschema.validate(instance=record, schema=schema)
        except jsonschema.ValidationError as exc:
            errors.append(f"{label}:{i}: schema validation failed: {exc.message}")


def main() -> int:
    errors: list = []

    try:
        contacts = load_jsonl(CONTACTS_PATH)
        detections = load_jsonl(DETECTIONS_PATH)
        audit = load_jsonl(AUDIT_PATH)
    except ValueError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    validate_records(contacts, load_schema("contact.schema.json"), "contacts.jsonl", errors)
    validate_records(detections, load_schema("detection.schema.json"), "detections.jsonl", errors)
    validate_records(audit, load_schema("audit.schema.json"), "audit.jsonl", errors)

    contact_ids = {c.get("contact_id") for c in contacts if "contact_id" in c}
    detection_by_id = {d.get("detection_id"): d for d in detections if "detection_id" in d}

    for i, detection in enumerate(detections, start=1):
        cid = detection.get("contact_id")
        if cid not in contact_ids:
            errors.append(
                f"detections.jsonl:{i}: contact_id '{cid}' not found in contacts.jsonl"
            )

    for i, entry in enumerate(audit, start=1):
        cid = entry.get("contact_id")
        if cid not in contact_ids:
            errors.append(
                f"audit.jsonl:{i}: contact_id '{cid}' not found in contacts.jsonl"
            )

        det_id = entry.get("detection_id")
        detection = detection_by_id.get(det_id)
        if detection is None:
            errors.append(
                f"audit.jsonl:{i}: detection_id '{det_id}' has no matching detection"
            )
        elif detection.get("status") not in ("approved", "applied"):
            errors.append(
                f"audit.jsonl:{i}: matching detection '{det_id}' has status "
                f"'{detection.get('status')}', expected 'approved' or 'applied'"
            )

    if errors:
        print("FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
