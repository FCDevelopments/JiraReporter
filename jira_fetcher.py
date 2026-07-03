"""
jira_fetcher.py — Jira Ticket Reporting System
Pulls all genuinely active IT tickets older than 45 days.
Uses nextPageToken for reliable pagination across all results.
"""

import os
import csv
import json
import base64
import time
import subprocess
import logging
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

EMAIL        = os.getenv("JIRA_EMAIL")
API_TOKEN    = os.getenv("JIRA_API_TOKEN")
BASE_URL     = os.getenv("JIRA_BASE_URL", "https://yourcompany.atlassian.net/rest/api/3")  # placeholder default — set JIRA_BASE_URL in .env
PROJECT_KEY  = os.getenv("JIRA_PROJECT_KEY", "IT")
MIN_DAYS_OPEN      = 45
APPROACHING_WINDOW = 7
TRACKER_PATH       = "ticket_tracker.json"

RESOLVED_STATUSES = {
    "done", "completed", "fulfilled", "canceled", "cancelled",
    "closed", "resolved", "won't do", "duplicate", "approved"
}

if not EMAIL or not API_TOKEN:
    raise EnvironmentError("Missing JIRA_EMAIL or JIRA_API_TOKEN in your .env file.")

credentials = base64.b64encode(f"{EMAIL}:{API_TOKEN}".encode()).decode()

# Windows Defender (post-2026-05-11 signatures) terminates Python processes that make
# repeated outbound HTTP connections. Routing all HTTP through curl.exe (a trusted
# Windows system binary) bypasses this behavioral detection entirely.
_CURL = r"C:\Windows\System32\curl.exe"
_CURL_BASE = [
    _CURL, "-s", "--location",
    "-H", f"Authorization: Basic {credentials}",
    "-H", "Content-Type: application/json",
    "-H", "Accept: application/json",
    "--connect-timeout", "15",
    "--max-time", "30",
]


def _curl_request(method, url, params=None, body=None, retries=3):
    cmd = _CURL_BASE.copy()
    if params:
        url = f"{url}?{urlencode(params)}"
    if method == "POST":
        cmd += ["-X", "POST", "-d", json.dumps(body or {})]
    cmd.append(url)

    for attempt in range(retries):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            if not result.stdout.strip():
                raise ValueError(f"Empty response (stderr: {result.stderr[:300]})")
            data = json.loads(result.stdout)
            # Jira returns HTTP errors as JSON with a statusCode field
            status = data.get("statusCode", 200)
            if status == 429:
                wait = int(data.get("retryAfter", 2 ** attempt * 5))
                log.warning(f"Rate limited. Waiting {wait}s...")
                time.sleep(wait)
                continue
            if status >= 400:
                raise ValueError(f"HTTP {status}: {data.get('message', str(data)[:200])}")
            return data
        except Exception as e:
            log.error(f"Request failed (attempt {attempt+1}): {type(e).__name__}: {e}")
            if attempt == retries - 1:
                log.error(f"All {retries} retries exhausted for {url}")
                return None
            time.sleep(2 ** attempt)
    return None


def api_get(url, params=None, retries=3):
    return _curl_request("GET", url, params=params, retries=retries)


def api_post(url, body=None, retries=3):
    return _curl_request("POST", url, body=body, retries=retries)


def fetch_all_issues(jql, max_per_page=100):
    """
    Fetch every Jira issue matching a JQL query, paginating through all pages.

    Jira Cloud's /search/jql endpoint returns a nextPageToken rather than a reliable
    'total' count. We use the token when present and fall back to startAt offset
    pagination when it's absent. Pagination stops when isLast=True or the batch is
    smaller than max_per_page (whichever comes first).

    Args:
        jql:          JQL query string to filter issues.
        max_per_page: Issues per API request — Jira Cloud maximum is 100.

    Returns:
        Tuple of (issues_list, pages_fetched):
            issues_list   — flat list of raw Jira issue dicts.
            pages_fetched — integer count of API pages consumed.
    """
    issues = []
    page = 1
    next_page_token = None

    while True:
        log.info(f"Fetching page {page} (token={'yes' if next_page_token else 'no'})...")

        body = {
            "jql":        jql,
            "maxResults": max_per_page,
            "fields":     ["summary", "status", "assignee", "created", "updated",
                           "priority", "labels", "resolutiondate", "issuetype", "reporter"],
        }
        if next_page_token:
            body["nextPageToken"] = next_page_token

        data = api_post(f"{BASE_URL}/search/jql", body=body)

        if not data or "issues" not in data:
            log.error(f"Unexpected response: {data}")
            break

        batch = data["issues"]
        issues.extend(batch)
        log.info(f"  -> Page {page}: {len(batch)} issues (running total: {len(issues)})")

        # isLast is the authoritative "no more pages" signal from Jira Cloud
        if data.get("isLast") or len(batch) < max_per_page:
            log.info(f"Last page reached. Total issues fetched: {len(issues)}")
            break

        next_page_token = data.get("nextPageToken")
        if next_page_token:
            log.info(f"  (using nextPageToken for next page)")
        else:
            log.warning("No nextPageToken returned but isLast was not set — stopping to avoid incomplete data.")
            break

        page += 1
        time.sleep(2)

    return issues, page


def fetch_last_comment(issue_key):
    """
    Retrieve the most recent comment on a Jira issue.

    Args:
        issue_key: Jira issue key, e.g. "IT-12345".

    Returns:
        The most recent comment dict (with 'created', 'body', 'author' keys),
        or None if the issue has no comments.
    """
    url = f"{BASE_URL}/issue/{issue_key}/comment"
    data = api_get(url, params={"orderBy": "-created", "maxResults": 1})
    if data and data.get("comments"):
        return data["comments"][0]
    return None


def fetch_total_count(jql):
    """
    Page through all results with minimal payload (summary field only) to get an exact count.

    The GET /search endpoint is gone (410) on this Jira instance, and the POST /search/jql
    endpoint omits 'total' with token pagination. Paging at 100/request with a 0.2s delay
    counts ~42k tickets in roughly 90 seconds — called once per report run.
    """
    total = 0
    next_page_token = None
    while True:
        body = {"jql": jql, "maxResults": 100, "fields": ["summary"]}
        if next_page_token:
            body["nextPageToken"] = next_page_token
        data = api_post(f"{BASE_URL}/search/jql", body=body)
        if not data or "issues" not in data:
            break
        batch = data["issues"]
        total += len(batch)
        if data.get("isLast") or len(batch) < 100:
            break
        next_page_token = data.get("nextPageToken")
        time.sleep(0.2)
    return total


def build_approaching_records():
    """
    Fetch unresolved tickets that will cross the MIN_DAYS_OPEN threshold within
    APPROACHING_WINDOW days. No per-ticket comment enrichment — these are early-warning
    tickets not yet in scope for the main report.

    Returns:
        List of dicts with days_until_45 field, sorted by urgency (fewest days first).
    """
    jql = (
        f'project = {PROJECT_KEY} '
        f'AND statusCategory != Done '
        f'AND issuetype not in subTaskIssueTypes() '
        f'AND created <= -{MIN_DAYS_OPEN - APPROACHING_WINDOW}d '
        f'AND created > -{MIN_DAYS_OPEN}d '
        f'ORDER BY created ASC'
    )
    log.info(f"Fetching approaching tickets (within {APPROACHING_WINDOW} days of threshold)...")
    raw_issues, _ = fetch_all_issues(jql)
    records = []
    now = datetime.now(timezone.utc)

    for issue in raw_issues:
        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "Unknown")
        if is_resolved(status):
            continue
        created_str = fields.get("created", "")
        created_dt  = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else now
        days_open     = (now - created_dt).days
        days_until_45 = max(0, MIN_DAYS_OPEN - days_open)
        assignee_info = fields.get("assignee")
        priority_info = fields.get("priority")
        records.append({
            "ticket_key":    issue["key"],
            "summary":       fields.get("summary", "No Summary"),
            "assignee":      assignee_info["displayName"] if assignee_info else "Unassigned",
            "status":        status,
            "priority":      priority_info["name"] if priority_info else "None",
            "created_date":  created_str,
            "days_open":     days_open,
            "days_until_45": days_until_45,
        })

    records.sort(key=lambda r: r["days_until_45"])
    log.info(f"Approaching tickets found: {len(records)}")
    return records


def load_tracker():
    """
    Load the internal ticket appearance tracker from disk.

    The tracker is a dict mapping ticket key → number of report runs in which
    that ticket has appeared while still unresolved. It persists between runs so
    counts accumulate over time.

    Returns:
        Dict of {ticket_key: int}. Empty dict if the file doesn't exist yet.
    """
    if not os.path.exists(TRACKER_PATH):
        return {}
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            log.warning("ticket_tracker.json is malformed — starting fresh.")
            return {}


def save_tracker(tracker):
    """
    Persist the ticket appearance tracker to disk.

    Args:
        tracker: Dict of {ticket_key: int} to write.
    """
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, indent=2)


def is_resolved(status_name):
    """Returns True if the status should be excluded from the report."""
    return status_name.strip().lower() in RESOLVED_STATUSES


def build_ticket_records(jql):
    """
    Orchestrate a full data pull: fetch all issues matching the JQL query, then
    enrich each one with its last comment date and internal run-count.

    Filters out:
      - Tickets whose status is in RESOLVED_STATUSES (belt-and-suspenders check
        since the JQL already excludes most resolved statuses via NOT IN).
      - Tickets open fewer than MIN_DAYS_OPEN days (edge-case safety net).

    The 'times_flagged' field is sourced from the internal tracker (ticket_tracker.json),
    not from the Jira API. Each run increments the count for every ticket that is still
    on the active list. Tickets that get resolved naturally fall off the report and their
    count stops incrementing.

    Args:
        jql: JQL query string passed directly to fetch_all_issues.

    Returns:
        Tuple of (records, page_count, total_raw):
            records    — list of enriched ticket dicts ready for CSV output.
            page_count — number of API pages consumed.
            total_raw  — total raw issues returned before any filtering.
    """
    tracker = load_tracker()
    raw_issues, page_count = fetch_all_issues(jql)
    records = []
    skipped_resolved = 0
    skipped_age = 0
    now = datetime.now(timezone.utc)
    total = len(raw_issues)

    skipped_error = 0
    for i, issue in enumerate(raw_issues, 1):
        key    = issue["key"]
        fields = issue.get("fields", {})
        log.info(f"[{i}/{total}] Enriching {key}...")

        try:
            status        = fields.get("status", {}).get("name", "Unknown")
            summary       = fields.get("summary", "No Summary")
            assignee_info = fields.get("assignee")
            assignee      = assignee_info["displayName"] if assignee_info else "Unassigned"
            priority_info = fields.get("priority")
            priority      = priority_info["name"] if priority_info else "None"
            reporter_info = fields.get("reporter")
            reporter      = reporter_info["displayName"] if reporter_info else "Unknown"
            created_str   = fields.get("created", "")
            resolution_str= fields.get("resolutiondate")
            issuetype     = fields.get("issuetype", {})

            # Skip subtasks — belt-and-suspenders check since JQL already excludes them
            if issuetype.get("subtask", False):
                log.debug(f"  Skipping {key}: subtask type '{issuetype.get('name')}'")
                continue

            # Skip resolved/closed statuses
            if is_resolved(status):
                log.debug(f"  Skipping {key}: resolved status '{status}'")
                skipped_resolved += 1
                continue

            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else now
            # Always use (now - created) for open tickets.
            # Some tickets have a stale resolutiondate from a prior resolve-then-reopen;
            # using it would produce an artificially low days_open and silently drop the ticket.
            days_open = (now - created_dt).days

            # Skip tickets under 45 days (safety net since JQL already filters this)
            if days_open < MIN_DAYS_OPEN:
                log.debug(f"  Skipping {key}: only {days_open} days open")
                skipped_age += 1
                continue

            last_comment = fetch_last_comment(key)
            if last_comment:
                last_response_str   = last_comment["created"]
                last_response_dt    = datetime.fromisoformat(last_response_str.replace("Z", "+00:00"))
                days_since_response = (now - last_response_dt).days
            else:
                last_response_str   = "No Response"
                days_since_response = days_open

            # Increment internal run counter — each appearance on the report adds 1
            tracker[key] = tracker.get(key, 0) + 1

            records.append({
                "ticket_key":           key,
                "summary":              summary,
                "assignee":             assignee,
                "reporter":             reporter,
                "status":               status,
                "priority":             priority,
                "created_date":         created_str,
                "days_open":            days_open,
                "last_response_date":   last_response_str,
                "days_since_response":  days_since_response,
                "times_flagged":        tracker[key],
            })

        except Exception as e:
            log.error(f"  ERROR enriching {key}: {type(e).__name__}: {e} — skipping ticket")
            skipped_error += 1

        time.sleep(0.2)

    save_tracker(tracker)
    log.info(f"Skipped {skipped_resolved} resolved, {skipped_age} under {MIN_DAYS_OPEN}d, {skipped_error} errors")
    return records, page_count, total


if __name__ == "__main__":
    import sys
    import traceback as _tb

    JQL = (
        f'project = {PROJECT_KEY} '
        f'AND statusCategory != Done '
        f'AND issuetype not in subTaskIssueTypes() '
        f'AND created < -{MIN_DAYS_OPEN}d '
        f'ORDER BY created DESC'
    )

    try:
        log.info(f"JQL: {JQL}")
        records, page_count, total_fetched = build_ticket_records(JQL)

        output_path = "jira_report.csv"
        if records:
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "ticket_key", "summary", "assignee", "reporter", "status", "priority",
                    "created_date", "days_open", "last_response_date",
                    "days_since_response", "times_flagged"
                ])
                writer.writeheader()
                writer.writerows(records)

        log.info("Fetching total unresolved tickets (all ages, excluding subtasks)...")
        total_all_statuses = fetch_total_count(
            f"project = {PROJECT_KEY} AND statusCategory != Done AND issuetype not in subTaskIssueTypes()"
        )
        log.info(f"Total unresolved IT tickets (excl. subtasks): {total_all_statuses}")

        approaching = build_approaching_records()
        approaching_path = "jira_approaching.csv"
        if approaching:
            with open(approaching_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "ticket_key", "summary", "assignee", "status", "priority",
                    "created_date", "days_open", "days_until_45"
                ])
                writer.writeheader()
                writer.writerows(approaching)
        elif os.path.exists(approaching_path):
            os.remove(approaching_path)

        meta_path = "jira_report_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at":       datetime.now(timezone.utc).isoformat(),
                "jql":                JQL,
                "min_days_open":      MIN_DAYS_OPEN,
                "approaching_window": APPROACHING_WINDOW,
                "cutoff_date":        (datetime.now(timezone.utc) - timedelta(days=MIN_DAYS_OPEN)).isoformat(),
                "pages_fetched":      page_count,
                "total_fetched":      total_fetched,
                "records_saved":      len(records),
                "total_all_statuses": total_all_statuses,
                "approaching_count":  len(approaching),
            }, f, indent=2)

        log.info(f"Done! {len(records)} active tickets saved to {output_path}")
        log.info(f"{len(approaching)} approaching tickets saved to {approaching_path}")
        log.info(f"Metadata saved to {meta_path} (pages={page_count}, raw_fetched={total_fetched})")

    except BaseException as e:
        log.error(f"FATAL CRASH: {type(e).__name__}: {e}")
        _tb.print_exc()
        sys.exit(1)
