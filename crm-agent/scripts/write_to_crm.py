#!/usr/bin/env python3
"""Push approved contact changes to the CRM, with a full audit trail.

CLI: contact_id, source_detection_id, approved_by, and one or more
--change field=new_value pairs.

For each change:
  1. An audit entry is written to state/audit.jsonl with
     crm_write_status="pending" *before* any CRM call is attempted.
  2. If config/pipeline.yaml write_mode is "draft": the CRM API is never
     called. The intended change is written to
     output/audit/[date]/[contact_id]-[field].md and the audit entry is
     left "pending" for a human to action later.
  3. If write_mode is "live": the contact field is staged in
     state/contacts.jsonl and the CRM is called via the connector
     configured in config/crm.yaml.
       - On success: the audit entry is updated to
         crm_write_status="success" with crm_api_response recorded.
       - On failure (including a missing/unconfigured connector, per
         CLAUDE.md section 3): the audit entry is updated to
         crm_write_status="failed", the in-state field is reverted to
         old_value, and the error is logged. A connector-unavailable
         failure additionally writes a manual-mode draft to
         output/alerts/.

Run as:
  python3 scripts/write_to_crm.py <contact_id> <source_detection_id> <approved_by> \\
      --change field=new_value [--change field2=new_value2 ...]
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = BASE_DIR / "state"
CONFIG_DIR = BASE_DIR / "config"
OUTPUT_DIR = BASE_DIR / "output"

CONTACTS_PATH = STATE_DIR / "contacts.jsonl"
AUDIT_PATH = STATE_DIR / "audit.jsonl"
PIPELINE_CONFIG_PATH = CONFIG_DIR / "pipeline.yaml"
CRM_CONFIG_PATH = CONFIG_DIR / "crm.yaml"


class ConnectorUnavailable(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def find_contact_index(contacts: list, contact_id: str):
    for i, c in enumerate(contacts):
        if c.get("contact_id") == contact_id:
            return i
    return None


def write_draft_change_file(contact_id: str, field: str, old_value, new_value, detection_id: str) -> Path:
    draft_dir = OUTPUT_DIR / "audit" / today_str()
    draft_dir.mkdir(parents=True, exist_ok=True)
    draft_path = draft_dir / f"{contact_id}-{field}.md"
    draft_path.write_text(
        f"# Draft CRM change\n\n"
        f"- contact_id: {contact_id}\n"
        f"- field: {field}\n"
        f"- old_value: {old_value}\n"
        f"- new_value: {new_value}\n"
        f"- source_detection_id: {detection_id}\n"
        f"- generated_at: {now_iso()}\n\n"
        f"write_mode is `draft`; this change has NOT been pushed to the CRM. "
        f"Review and re-run with write_mode=live to apply it.\n"
    )
    return draft_path


def write_connector_unavailable_alert(contact_id: str, field: str, reason: str) -> Path:
    alerts_dir = OUTPUT_DIR / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    alert_path = alerts_dir / f"{today_str()}-{contact_id}-{field}-connector-unavailable.md"
    alert_path.write_text(
        f"# CRM connector unavailable\n\n"
        f"- contact_id: {contact_id}\n"
        f"- field: {field}\n"
        f"- reason: {reason}\n"
        f"- generated_at: {now_iso()}\n\n"
        f"Switched to manual mode per CLAUDE.md section 3. This change was "
        f"NOT applied to the CRM. A human must apply it manually or fix the "
        f"connector configuration in config/crm.yaml.\n"
    )
    return alert_path


def call_crm_api(crm_config: dict, contact: dict, field: str, new_value) -> str:
    """Call the configured CRM connector. Raises ConnectorUnavailable if no
    connector/provider is configured, since this scaffold ships without a
    live integration wired up."""
    provider = crm_config.get("provider")
    api_via = crm_config.get("api_via")

    if not provider or not api_via:
        raise ConnectorUnavailable(
            "config/crm.yaml has no provider/api_via configured"
        )
    if api_via == "mcp" and not crm_config.get("connector_name"):
        raise ConnectorUnavailable("api_via is 'mcp' but no connector_name is configured")

    raise ConnectorUnavailable(
        f"no live '{provider}' integration is wired up in this scaffold "
        f"(api_via={api_via}); implement call_crm_api before using write_mode=live"
    )


def process_change(
    contact_id: str,
    field: str,
    new_value: str,
    detection_id: str,
    approved_by: str,
    contacts: list,
    pipeline_config: dict,
    crm_config: dict,
) -> bool:
    """Returns True if state was written to, False otherwise."""
    contact_index = find_contact_index(contacts, contact_id)
    if contact_index is None:
        print(f"ERROR: contact_id '{contact_id}' not found", file=sys.stderr)
        return False

    contact = contacts[contact_index]
    old_value = contact.get(field)
    write_mode = pipeline_config.get("write_mode", "draft")

    audit_entry = {
        "audit_id": f"audit-{uuid.uuid4().hex[:12]}",
        "contact_id": contact_id,
        "crm_record_id": contact.get("crm_record_id", ""),
        "detection_id": detection_id,
        "field": field,
        "old_value": old_value,
        "new_value": new_value,
        "write_mode": write_mode,
        "approved_by": approved_by,
        "crm_write_status": "pending",
        "crm_api_response": None,
        "timestamp": now_iso(),
    }
    append_jsonl(AUDIT_PATH, audit_entry)

    if write_mode == "draft":
        draft_path = write_draft_change_file(contact_id, field, old_value, new_value, detection_id)
        print(f"DRAFT: wrote {draft_path}; audit entry left 'pending'")
        return False

    # write_mode == "live": stage the change, then attempt the CRM call.
    contact[field] = new_value
    contact["updated_at"] = now_iso()
    contacts[contact_index] = contact
    write_jsonl(CONTACTS_PATH, contacts)

    try:
        response = call_crm_api(crm_config, contact, field, new_value)
        audit_entry["crm_write_status"] = "success"
        audit_entry["crm_api_response"] = response
        print(f"OK: {contact_id}.{field} -> '{new_value}' pushed to CRM")
    except ConnectorUnavailable as exc:
        contact[field] = old_value
        contacts[contact_index] = contact
        write_jsonl(CONTACTS_PATH, contacts)
        audit_entry["crm_write_status"] = "failed"
        audit_entry["crm_api_response"] = str(exc)
        write_connector_unavailable_alert(contact_id, field, str(exc))
        print(f"FAILED (connector unavailable): {exc}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - any CRM call failure triggers rollback
        contact[field] = old_value
        contacts[contact_index] = contact
        write_jsonl(CONTACTS_PATH, contacts)
        audit_entry["crm_write_status"] = "failed"
        audit_entry["crm_api_response"] = str(exc)
        print(f"FAILED: {exc}", file=sys.stderr)

    _update_last_audit_entry(audit_entry)
    return True


def _update_last_audit_entry(updated_entry: dict) -> None:
    entries = load_jsonl(AUDIT_PATH)
    for i in range(len(entries) - 1, -1, -1):
        if entries[i]["audit_id"] == updated_entry["audit_id"]:
            entries[i] = updated_entry
            break
    write_jsonl(AUDIT_PATH, entries)


def parse_change(raw: str) -> tuple:
    if "=" not in raw:
        raise argparse.ArgumentTypeError(f"--change must be field=new_value, got '{raw}'")
    field, value = raw.split("=", 1)
    return field, value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contact_id")
    parser.add_argument("source_detection_id")
    parser.add_argument("approved_by")
    parser.add_argument(
        "--change",
        action="append",
        required=True,
        type=parse_change,
        help="field=new_value; may be repeated for multiple fields",
    )
    args = parser.parse_args()

    contacts = load_jsonl(CONTACTS_PATH)
    pipeline_config = load_yaml(PIPELINE_CONFIG_PATH)
    crm_config = load_yaml(CRM_CONFIG_PATH)

    any_failure = False
    for field, new_value in args.change:
        process_change(
            args.contact_id,
            field,
            new_value,
            args.source_detection_id,
            args.approved_by,
            contacts,
            pipeline_config,
            crm_config,
        )
        contacts = load_jsonl(CONTACTS_PATH)

    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
