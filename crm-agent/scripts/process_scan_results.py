#!/usr/bin/env python3
"""Wire candidate-scanner output into state.

Reads every file in output/scanner/[today]/ (JSON objects matching the
schema in prompts/candidate_scanner.md) and, for each one:

- scanner_verdict == "skip": builds a low_risk "enrichment" detection for
  the last_verified_at bump and applies it via scripts/update_contact.py.
  update_contact.py recomputes decay_score as a coupled side effect of
  that call -- this script never touches decay_score directly.
- scanner_verdict == "investigate": appends the contact_id (plus the
  scanner's trigger_reasons, for context) to
  state/queue/validator-[today].jsonl, for the deeper pass in
  prompts/detection_validator.md.

After processing, runs scripts/validate_state.py and reports:
- contacts scanned / skipped / queued
- how many times each source came back "unavailable"
- which connectors are the actual gap (so a human can go connect them)

Run as: python3 scripts/process_scan_results.py [--date YYYY-MM-DD]
"""

import argparse
import json
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_SCANNER_DIR = BASE_DIR / "output" / "scanner"
QUEUE_DIR = BASE_DIR / "state" / "queue"
DETECTIONS_PATH = BASE_DIR / "state" / "detections.jsonl"
VALIDATE_SCRIPT = BASE_DIR / "scripts" / "validate_state.py"
UPDATE_SCRIPT = BASE_DIR / "scripts" / "update_contact.py"

SOURCE_TO_CONNECTOR = {
    "linkedin_profile": "Apollo or Clay MCP (falls back to web search)",
    "linkedin_activity": "Apollo or Clay MCP (falls back to web search)",
    "gmail_bounces": "Gmail MCP",
    "previous_company_page": "web search (no dedicated connector)",
    "press_news": "web search (no dedicated connector)",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")


def append_detection(detection: dict) -> None:
    append_jsonl(DETECTIONS_PATH, detection)


def process_skip(scan: dict) -> bool:
    contact_id = scan["contact_id"]
    detection = {
        "detection_id": f"det-scan-verify-{uuid.uuid4().hex[:10]}",
        "contact_id": contact_id,
        "detection_type": "enrichment",
        "evidence": [
            {
                "source": "candidate_scanner",
                "url": None,
                "date": today_str(),
                "quote": (
                    f"Scanner verdict=skip; sources_checked="
                    f"{json.dumps(scan.get('sources_checked', []))}"
                ),
            }
        ],
        "confidence": "high",
        "proposed_changes": {"last_verified_at": now_iso()},
        "requires_approval": False,
        "field_risk_category": "low_risk",
        "created_at": now_iso(),
        "status": "approved",
    }
    append_detection(detection)

    result = subprocess.run(
        [
            sys.executable, str(UPDATE_SCRIPT),
            contact_id, "last_verified_at",
            detection["proposed_changes"]["last_verified_at"],
            detection["detection_id"],
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  FAILED to verify {contact_id}: {result.stderr.strip()}", file=sys.stderr)
        return False
    print(f"  {result.stdout.strip()}")
    return True


def process_investigate(scan: dict, queue_path: Path) -> None:
    append_jsonl(queue_path, {
        "contact_id": scan["contact_id"],
        "trigger_reasons": scan.get("trigger_reasons", []),
        "last_movement_date": scan.get("last_movement_date"),
        "queued_at": now_iso(),
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=today_str(), help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    scan_dir = OUTPUT_SCANNER_DIR / args.date
    queue_path = QUEUE_DIR / f"validator-{args.date}.jsonl"

    if not scan_dir.exists():
        print(f"No scanner output directory found: {scan_dir}", file=sys.stderr)
        return 1

    scan_files = sorted(scan_dir.glob("*.json"))
    if not scan_files:
        print(f"No scanner output files found in {scan_dir}", file=sys.stderr)
        return 1

    scanned = 0
    skipped = 0
    queued = 0
    source_status_counts = {src: Counter() for src in SOURCE_TO_CONNECTOR}

    for path in scan_files:
        with open(path) as f:
            scan = json.load(f)
        scanned += 1

        for source_entry in scan.get("sources_checked", []):
            src = source_entry.get("source")
            status = source_entry.get("status")
            if src in source_status_counts:
                source_status_counts[src][status] += 1

        verdict = scan.get("scanner_verdict")
        if verdict == "skip":
            if process_skip(scan):
                skipped += 1
        elif verdict == "investigate":
            process_investigate(scan, queue_path)
            queued += 1
        else:
            print(f"  WARNING: unrecognized scanner_verdict '{verdict}' for {scan.get('contact_id')}", file=sys.stderr)

    validate_result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT)], capture_output=True, text=True
    )
    print(validate_result.stdout.strip())
    if validate_result.returncode != 0:
        print(validate_result.stderr.strip(), file=sys.stderr)

    print(f"\nContacts scanned: {scanned}")
    print(f"Skipped (verified, no signal): {skipped}")
    print(f"Queued for validator: {queued}")

    print("\nSources unavailable (per source):")
    connector_gaps = []
    for src, connector in SOURCE_TO_CONNECTOR.items():
        unavailable = source_status_counts[src].get("unavailable", 0)
        print(f"  {src}: {unavailable} unavailable")
        if unavailable > 0:
            connector_gaps.append((src, connector, unavailable))

    print("\nConnector gaps to flag for the human:")
    if connector_gaps:
        for src, connector, count in connector_gaps:
            print(f"  - {src} was unavailable {count}x -- needs: {connector}")
    else:
        print("  none -- every source resolved to 'ok' or 'not_found'")

    return validate_result.returncode


if __name__ == "__main__":
    sys.exit(main())
