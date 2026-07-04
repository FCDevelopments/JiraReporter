"""
export_for_snowflake.py
Combines jira_report.csv and jira_approaching.csv into a single
snowflake_upload.csv that matches the JIRA_TICKETS table schema exactly.

Run: python export_for_snowflake.py
Output: snowflake_upload.csv
"""

import csv
import os
from datetime import date, datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_CSV       = os.path.join(SCRIPT_DIR, "jira_report.csv")
APPROACHING_CSV = os.path.join(SCRIPT_DIR, "jira_approaching.csv")
ALL_CSV        = os.path.join(SCRIPT_DIR, "jira_report_all.csv")
OUT_CSV        = os.path.join(SCRIPT_DIR, "snowflake_upload.csv")

TODAY = date.today()

SNOWFLAKE_COLUMNS = [
    "ticket_key", "summary", "assignee", "reporter", "status", "priority",
    "created_date", "days_open", "last_response_date", "days_since_response",
    "times_flagged", "is_approaching", "days_until_45", "last_updated"
]


def clean_date(value):
    """Return YYYY-MM-DD from either a full ISO timestamp or plain date string."""
    if not value or value.strip().lower() in ("", "no response", "none", "null"):
        return ""
    return (value or "")[:10]


def parse_int(value, default=0):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def load_main_tickets():
    tickets = {}
    with open(MAIN_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row.get("ticket_key", "").strip()
            if not key:
                continue

            lrd = clean_date(row.get("last_response_date", ""))
            dsr_raw = row.get("days_since_response", "")
            dsr = parse_int(dsr_raw) if dsr_raw and dsr_raw.strip().lower() not in ("no response", "", "none") else ""

            days_open = parse_int(row.get("days_open", 0))
            days_until_45 = 45 - days_open

            tickets[key] = {
                "ticket_key":          key,
                "summary":             (row.get("summary") or "")[:1000],
                "assignee":            row.get("assignee") or "Unassigned",
                "reporter":            row.get("reporter") or "Unknown",
                "status":              row.get("status") or "Unknown",
                "priority":            row.get("priority") or "Medium",
                "created_date":        clean_date(row.get("created_date", "")),
                "days_open":           days_open,
                "last_response_date":  lrd,
                "days_since_response": dsr,
                "times_flagged":       parse_int(row.get("times_flagged", 0)),
                "is_approaching":      "FALSE",
                "days_until_45":       days_until_45,
                "last_updated":        TODAY.isoformat(),
            }
    return tickets


def load_approaching_tickets(existing_keys):
    """Load approaching tickets that aren't already in the main 45+ set."""
    approaching = {}
    if not os.path.exists(APPROACHING_CSV):
        return approaching

    with open(APPROACHING_CSV, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = row.get("ticket_key", "").strip()
            if not key or key in existing_keys:
                continue

            days_open    = parse_int(row.get("days_open", 0))
            days_until_45 = parse_int(row.get("days_until_45", 45 - days_open))

            approaching[key] = {
                "ticket_key":          key,
                "summary":             (row.get("summary") or "")[:1000],
                "assignee":            row.get("assignee") or "Unassigned",
                "reporter":            "Unknown",
                "status":              row.get("status") or "Unknown",
                "priority":            row.get("priority") or "Medium",
                "created_date":        clean_date(row.get("created_date", "")),
                "days_open":           days_open,
                "last_response_date":  "",
                "days_since_response": "",
                "times_flagged":       0,
                "is_approaching":      "TRUE",
                "days_until_45":       days_until_45,
                "last_updated":        TODAY.isoformat(),
            }
    return approaching


def main():
    print("Reading main 45+ day tickets...")
    tickets = load_main_tickets()
    print(f"  Loaded {len(tickets)} tickets from jira_report.csv")

    print("Reading approaching tickets...")
    approaching = load_approaching_tickets(set(tickets.keys()))
    print(f"  Loaded {len(approaching)} additional approaching tickets")

    # Mark approaching flag on 45+ tickets that also qualify
    for t in tickets.values():
        if 0 <= t["days_until_45"] <= 7:
            t["is_approaching"] = "TRUE"

    all_tickets = list(tickets.values()) + list(approaching.values())
    all_tickets.sort(key=lambda t: t["days_open"], reverse=True)

    print(f"Writing {len(all_tickets)} total rows to snowflake_upload.csv...")
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SNOWFLAKE_COLUMNS)
        writer.writeheader()
        writer.writerows(all_tickets)

    print(f"\nDone! File saved to: {OUT_CSV}")
    print(f"Total rows: {len(all_tickets)}")
    print(f"  45+ day tickets : {len(tickets)}")
    print(f"  Approaching only : {len(approaching)}")
    print(f"\nUpload this file to Snowflake:")
    print(f"  Snowsight -> + New -> Upload local files -> select snowflake_upload.csv")
    print(f"  Table name: JIRA_TICKETS")


if __name__ == "__main__":
    main()
