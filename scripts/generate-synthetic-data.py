"""Generate the SYNTHETIC request records used by the record-lookup tool (config/sample-data.json).

Deterministic (fixed seed) so demos and tests are reproducible. Records SR-1001..SR-1005 are
kept verbatim because tests and walkthroughs reference them; the rest are generated.

    python scripts/generate-synthetic-data.py            # writes config/sample-data.json
    python scripts/generate-synthetic-data.py --count 40 # more records
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "config" / "sample-data.json"

FIXED = [
    {"id": "SR-1001", "status": "In progress", "summary": "Access review is awaiting a final approval step.", "last_updated": "2026-09-24", "owner_team": "Access Operations"},
    {"id": "SR-1002", "status": "Resolved", "summary": "Configuration update was completed and verified.", "last_updated": "2026-09-22", "owner_team": "Platform Support"},
    {"id": "SR-1003", "status": "Waiting on requester", "summary": "Additional details are needed before work can continue.", "last_updated": "2026-09-23", "owner_team": "Intake Desk"},
    {"id": "SR-1004", "status": "Scheduled", "summary": "Maintenance window is scheduled for the next business day.", "last_updated": "2026-09-25", "owner_team": "Service Engineering"},
    {"id": "SR-1005", "status": "Under review", "summary": "Support team is validating impact and next steps.", "last_updated": "2026-09-25", "owner_team": "Support Coordination"},
]

# (summary, owner team, typical priority, knowledge article that explains it)
SCENARIOS = [
    ("New laptop request is waiting for manager approval.", "Device Services", "P4", "kb/hardware-request"),
    ("Replacement laptop has shipped and should arrive in two business days.", "Device Services", "P3", "kb/hardware-request"),
    ("VPN certificate error is being investigated by the network team.", "Network Operations", "P2", "kb/vpn"),
    ("Remote desktop access was approved and is being configured.", "Network Operations", "P4", "kb/remote-desktop"),
    ("Shared mailbox access was granted; it may take two hours to appear.", "Collaboration Services", "P4", "kb/shared-mailbox"),
    ("Software security review is in progress for the requested application.", "Application Security", "P4", "kb/software-install"),
    ("Software license was assigned and is ready to use.", "Software Asset Management", "P4", "kb/software-license"),
    ("Application crash was reproduced; a fix is planned for the next update.", "Application Support", "P3", "kb/app-crash"),
    ("Lost phone was reported; work data has been wiped and a replacement is on order.", "Security Operations", "P2", "kb/lost-device"),
    ("Suspicious email report was reviewed; no action is needed from you.", "Security Operations", "P3", "kb/phishing"),
    ("USB storage exception is waiting for security approval.", "Security Operations", "P4", "kb/usb-storage"),
    ("Printer on floor three is waiting for a technician visit.", "Facilities IT", "P3", "kb/printer"),
    ("Meeting room display was replaced and tested.", "Facilities IT", "P3", "kb/meeting-rooms"),
    ("Badge was reactivated at reception.", "Workplace Services", "P4", "kb/badge"),
    ("Travel request for remote work abroad is waiting for security review.", "Security Operations", "P4", "kb/remote-travel"),
    ("Departure request received; device return label has been emailed.", "Device Services", "P4", "kb/offboarding"),
    ("Mailbox archive was enabled after the mailbox reached its limit.", "Collaboration Services", "P3", "kb/mailbox-full"),
    ("Multifactor registration was reset with a temporary access pass.", "Access Operations", "P2", "kb/mfa-lost-phone"),
    ("Repeated account lockouts were traced to an old saved password on a phone.", "Access Operations", "P3", "kb/account-unlock"),
    ("Loaner laptop was issued while the primary device is repaired.", "Device Services", "P3", "kb/loaner-devices"),
]
STATUSES = ["Open", "In progress", "Waiting on requester", "Scheduled", "Resolved", "Closed"]


def generate(count: int, seed: int = 20260929) -> list[dict]:
    rng = random.Random(seed)
    today = date(2026, 9, 29)
    records = [dict(r) for r in FIXED]
    for index in range(max(0, count - len(FIXED))):
        summary, team, priority, article = SCENARIOS[index % len(SCENARIOS)]
        opened = today - timedelta(days=rng.randint(1, 20))
        status = "Resolved" if "granted" in summary or "was " in summary else rng.choice(STATUSES[:4])
        records.append(
            {
                "id": f"SR-{1006 + index}",
                "status": status,
                "summary": summary,
                "priority": priority,
                "opened": opened.isoformat(),
                "last_updated": min(today, opened + timedelta(days=rng.randint(0, 5))).isoformat(),
                "owner_team": team,
                "related_article": article,
            }
        )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    data = {
        "_note": "SYNTHETIC request records for the record-lookup tool (fictional). Regenerate with scripts/generate-synthetic-data.py.",
        "records": generate(args.count),
    }
    Path(args.out).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(data['records'])} records to {args.out}")


if __name__ == "__main__":
    main()
