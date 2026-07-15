#!/usr/bin/env python3
"""Push approved contact changes to the CRM, with a full audit trail.

This script cannot call an MCP connector itself -- MCP tools (e.g.
mcp__HubSpot__manage_crm_objects) are only reachable from inside an agent
session, not from a plain Python subprocess. So when config/crm.yaml has
api_via: mcp, the live write is a two-step handoff between this script
and the agent:

  1. `push` stages the change and writes a "pending" audit entry, then
     (in live+mcp mode) prints the exact MCP call the agent must make.
     It does NOT claim success -- crm_write_status stays "pending".
  2. The agent makes that MCP call itself.
  3. The agent runs `mark-result` with the outcome, which finalizes the
     audit entry to "success" or "failed" and, on failure, reverts the
     in-state field back to old_value.

If config/crm.yaml has api_via: direct instead, `push` calls
call_crm_api() directly and resolves success/failed/rollback in one
step -- no agent handoff, no `mark-result` needed. (call_crm_api() is a
stub in this scaffold; wire it to a real HTTP client + API token before
using api_via: direct.)

If config/pipeline.yaml write_mode is "draft": no CRM call is attempted
in either mode. The intended change is written to
output/audit/[date]/[contact_id]-[field].md and the audit entry is left
"pending" for a human to action later.

Run as:
  python3 scripts/write_to_crm.py push <contact_id> <source_detection_id> <approved_by> \\
      --change field=new_value [--change field2=new_value2 ...]

  python3 scripts/write_to_crm.py mark-result <audit_id> --status success --response '...'
  python3 scripts/write_to_crm.py mark-result <audit_id> --status failed --response '...'
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

MCP_TOOL_BY_PROVIDER = {
    "hubspot": "mcp__HubSpot__manage_crm_objects",
}

# contact.schema.json property name -> config/crm.yaml field_mapping key.
# The two use different vocabularies on purpose (schema names are internal
# state fields; crm.yaml names are the human-facing "what CRM field does
# this logical concept map to" labels), so a lookup has to go through this.
CONTACT_FIELD_TO_CRM_KEY = {
    "email": "email",
    "phone": "phone",
    "title": "job_title",
    "company": "company_name",
    "decay_score": "custom_decay_score",
}


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
    """Call the configured CRM connector directly over HTTP. Only used when
    api_via: direct. Raises ConnectorUnavailable since no HTTP client/API
    token is wired up in this scaffold yet."""
    provider = crm_config.get("provider")
    if not provider:
        raise ConnectorUnavailable("config/crm.yaml has no provider configured")

    raise ConnectorUnavailable(
        f"no direct HTTP integration is wired up for '{provider}' in this scaffold; "
        f"implement call_crm_api with a real API token before using api_via: direct"
    )


def print_mcp_action_required(audit_entry: dict, crm_config: dict, contact: dict, field: str, new_value: str) -> None:
    provider = crm_config.get("provider")
    tool_name = MCP_TOOL_BY_PROVIDER.get(provider, "<no known MCP tool for this provider>")
    crm_key = CONTACT_FIELD_TO_CRM_KEY.get(field, field)
    crm_field = (crm_config.get("field_mapping") or {}).get(crm_key)
    contact_object = (crm_config.get("object_mapping") or {}).get("contact_object", "contacts")

    print("MCP_ACTION_REQUIRED:")
    print(f"  audit_id: {audit_entry['audit_id']}")
    print(f"  tool: {tool_name}")
    print(f"  objectType: {contact_object}")
    print(f"  objectId: {contact.get('crm_record_id')}")
    if crm_field:
        print(f"  properties: {{\"{crm_field}\": \"{new_value}\"}}")
    else:
        print(
            f"  properties: <no field_mapping entry for '{field}' in config/crm.yaml -- "
            f"add one before making this call>"
        )
    print(
        "  After the agent makes this call, resolve the audit entry with:\n"
        f"    python3 scripts/write_to_crm.py mark-result {audit_entry['audit_id']} "
        f"--status success --response '<hubspot response summary>'\n"
        "  or, if the call fails:\n"
        f"    python3 scripts/write_to_crm.py mark-result {audit_entry['audit_id']} "
        f"--status failed --response '<error message>'"
    )


def cmd_push(args) -> int:
    contacts = load_jsonl(CONTACTS_PATH)
    pipeline_config = load_yaml(PIPELINE_CONFIG_PATH)
    crm_config = load_yaml(CRM_CONFIG_PATH)
    write_mode = pipeline_config.get("write_mode", "draft")
    api_via = crm_config.get("api_via")

    exit_code = 0
    for field, new_value in args.change:
        contact_index = find_contact_index(contacts, args.contact_id)
        if contact_index is None:
            print(f"ERROR: contact_id '{args.contact_id}' not found", file=sys.stderr)
            exit_code = 1
            continue

        contact = contacts[contact_index]
        old_value = contact.get(field)

        audit_entry = {
            "audit_id": f"audit-{uuid.uuid4().hex[:12]}",
            "contact_id": args.contact_id,
            "crm_record_id": contact.get("crm_record_id", ""),
            "detection_id": args.source_detection_id,
            "field": field,
            "old_value": old_value,
            "new_value": new_value,
            "write_mode": write_mode,
            "approved_by": args.approved_by,
            "crm_write_status": "pending",
            "crm_api_response": None,
            "timestamp": now_iso(),
        }
        append_jsonl(AUDIT_PATH, audit_entry)

        if write_mode == "draft":
            draft_path = write_draft_change_file(args.contact_id, field, old_value, new_value, args.source_detection_id)
            print(f"DRAFT: wrote {draft_path}; audit entry left 'pending'")
            continue

        # write_mode == "live": stage the change first.
        contact[field] = new_value
        contact["updated_at"] = now_iso()
        contacts[contact_index] = contact
        write_jsonl(CONTACTS_PATH, contacts)

        if api_via == "mcp":
            print(f"STAGED: {args.contact_id}.{field} -> '{new_value}' in state; CRM push pending agent action")
            print_mcp_action_required(audit_entry, crm_config, contact, field, new_value)
            continue

        # api_via == "direct" (or anything else): resolve in one step.
        try:
            response = call_crm_api(crm_config, contact, field, new_value)
            audit_entry["crm_write_status"] = "success"
            audit_entry["crm_api_response"] = response
            print(f"OK: {args.contact_id}.{field} -> '{new_value}' pushed to CRM")
        except ConnectorUnavailable as exc:
            contact[field] = old_value
            contacts[contact_index] = contact
            write_jsonl(CONTACTS_PATH, contacts)
            audit_entry["crm_write_status"] = "failed"
            audit_entry["crm_api_response"] = str(exc)
            write_connector_unavailable_alert(args.contact_id, field, str(exc))
            print(f"FAILED (connector unavailable): {exc}", file=sys.stderr)
            exit_code = 1
        except Exception as exc:  # noqa: BLE001 - any CRM call failure triggers rollback
            contact[field] = old_value
            contacts[contact_index] = contact
            write_jsonl(CONTACTS_PATH, contacts)
            audit_entry["crm_write_status"] = "failed"
            audit_entry["crm_api_response"] = str(exc)
            print(f"FAILED: {exc}", file=sys.stderr)
            exit_code = 1

        _update_audit_entry(audit_entry)

    return exit_code


def cmd_mark_result(args) -> int:
    entries = load_jsonl(AUDIT_PATH)
    entry_index = next((i for i, e in enumerate(entries) if e.get("audit_id") == args.audit_id), None)
    if entry_index is None:
        print(f"ERROR: audit_id '{args.audit_id}' not found", file=sys.stderr)
        return 1

    entry = entries[entry_index]
    if entry["crm_write_status"] != "pending":
        print(
            f"ERROR: audit entry '{args.audit_id}' is already '{entry['crm_write_status']}', "
            f"expected 'pending'",
            file=sys.stderr,
        )
        return 1

    entry["crm_write_status"] = args.status
    entry["crm_api_response"] = args.response
    entries[entry_index] = entry
    write_jsonl(AUDIT_PATH, entries)

    if args.status == "failed":
        contacts = load_jsonl(CONTACTS_PATH)
        contact_index = find_contact_index(contacts, entry["contact_id"])
        if contact_index is not None:
            contacts[contact_index][entry["field"]] = entry["old_value"]
            contacts[contact_index]["updated_at"] = now_iso()
            write_jsonl(CONTACTS_PATH, contacts)
        print(
            f"REVERTED: {entry['contact_id']}.{entry['field']} back to "
            f"'{entry['old_value']}' (CRM write failed: {args.response})"
        )
    else:
        print(f"OK: audit entry '{args.audit_id}' marked success")

    return 0


def _update_audit_entry(updated_entry: dict) -> None:
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    push_parser = subparsers.add_parser("push", help="Stage a change and either push it directly or request an MCP handoff")
    push_parser.add_argument("contact_id")
    push_parser.add_argument("source_detection_id")
    push_parser.add_argument("approved_by")
    push_parser.add_argument(
        "--change",
        action="append",
        required=True,
        type=parse_change,
        help="field=new_value; may be repeated for multiple fields",
    )
    push_parser.set_defaults(func=cmd_push)

    mark_parser = subparsers.add_parser("mark-result", help="Resolve a pending audit entry after an agent-performed MCP call")
    mark_parser.add_argument("audit_id")
    mark_parser.add_argument("--status", choices=["success", "failed"], required=True)
    mark_parser.add_argument("--response", required=True, help="CRM API response summary or error message")
    mark_parser.set_defaults(func=cmd_mark_result)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
