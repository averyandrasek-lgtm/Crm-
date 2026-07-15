#!/usr/bin/env python3
"""Load contacts.csv into state/contacts.jsonl.

Reads contacts.csv (headers: crm_record_id, first_name, last_name, email,
company, title, linkedin_url) and writes one record per contact to
state/contacts.jsonl with a computed contact_id slug, decay_score=0.0,
last_verified_at=null, and created_at=updated_at=now.

Every record is validated against schemas/contact.schema.json before it is
written. The loader is idempotent: if a contact_id already exists in
state/contacts.jsonl, only the fields explicitly provided in the CSV row
are updated, and a populated field is never overwritten with an empty one.

Run as: python3 scripts/load_contacts.py [--csv contacts.csv]
"""

import argparse
import csv
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CSV = BASE_DIR / "contacts.csv"
CONTACTS_JSONL = BASE_DIR / "state" / "contacts.jsonl"
SCHEMA_PATH = BASE_DIR / "schemas" / "contact.schema.json"
LOG_DIR = BASE_DIR / "logs"


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def make_contact_id(first_name: str, last_name: str, company: str, crm_record_id: str) -> str:
    """Build the firstname-lastname-companyslug slug when all three are
    present. If any are missing (real for bulk CRM imports where a contact
    has no name or company on file), fall back to a crm_record_id-suffixed
    slug so distinct blank/partial contacts never collide on contact_id."""
    parts = [slugify(p) for p in (first_name, last_name, company) if p and slugify(p)]
    if first_name and last_name and company:
        return "-".join(parts)
    base = "-".join(parts) if parts else "contact"
    return f"{base}-{slugify(str(crm_record_id))}"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = LOG_DIR / f"load-{date_str}.log"
    logger = logging.getLogger("load_contacts")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler(sys.stdout))
    return logger


def load_schema() -> dict:
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def load_existing_contacts() -> dict:
    contacts = {}
    if CONTACTS_JSONL.exists():
        with open(CONTACTS_JSONL) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                contacts[record["contact_id"]] = record
    return contacts


def merge_record(existing: dict, incoming: dict, timestamp: str) -> dict:
    """Update only fields explicitly provided in the CSV, never overwrite
    a populated field with an empty one."""
    merged = dict(existing)
    for key, value in incoming.items():
        if value is None or value == "":
            continue
        merged[key] = value
    merged["updated_at"] = timestamp
    return merged


def build_new_record(row: dict, contact_id: str, timestamp: str) -> dict:
    return {
        "contact_id": contact_id,
        "first_name": row.get("first_name", "").strip() or None,
        "last_name": row.get("last_name", "").strip() or None,
        "email": row.get("email") or None,
        "phone": row.get("phone") or None,
        "linkedin_url": row.get("linkedin_url") or None,
        "company": row.get("company", "").strip() or None,
        "company_domain": None,
        "title": row.get("title", "").strip() or None,
        "role_category": row.get("role_category") or "other",
        "crm_record_id": row["crm_record_id"].strip(),
        "open_deal_ids": [],
        "last_verified_at": None,
        "decay_score": 0.0,
        "job_history": [],
        "bounce_history": [],
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Path to contacts.csv")
    args = parser.parse_args()

    logger = setup_logging()
    schema = load_schema()
    existing_contacts = load_existing_contacts()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error("CSV not found: %s", csv_path)
        return 1

    timestamp = now_iso()
    written = 0
    updated = 0
    errors = 0

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contact_id = make_contact_id(
                row.get("first_name", ""), row.get("last_name", ""), row.get("company", ""),
                row["crm_record_id"],
            )
            if contact_id in existing_contacts:
                record = merge_record(existing_contacts[contact_id], row, timestamp)
                action = "updated"
            else:
                record = build_new_record(row, contact_id, timestamp)
                action = "created"

            try:
                jsonschema.validate(instance=record, schema=schema)
            except jsonschema.ValidationError as exc:
                logger.error("Validation failed for %s: %s", contact_id, exc.message)
                errors += 1
                continue

            existing_contacts[contact_id] = record
            if action == "created":
                written += 1
                logger.info("Created contact %s", contact_id)
            else:
                updated += 1
                logger.info("Updated contact %s", contact_id)

    with open(CONTACTS_JSONL, "w") as f:
        for record in existing_contacts.values():
            f.write(json.dumps(record) + "\n")

    logger.info(
        "Load complete: %d created, %d updated, %d errors", written, updated, errors
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
