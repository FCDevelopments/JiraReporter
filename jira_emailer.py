"""
jira_emailer.py — Send Jira report digest via Outlook (Windows COM).
Reads jira_report.csv + jira_report_metadata.json and emails an HTML summary.

Usage:
    python jira_emailer.py
"""

import csv
import html
import json
import os
import sys
from collections import Counter
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

CSV_PATH   = "jira_report.csv"
META_PATH  = "jira_report_metadata.json"
JIRA_BASE  = os.getenv("JIRA_BASE_URL", "https://yourcompany.atlassian.net/rest/api/3")  # placeholder default — set JIRA_BASE_URL in .env
EMAIL_TO   = os.getenv("EMAIL_TO", "")  # e.g. it-team@yourcompany.com — set in .env
EMAIL_CC   = os.getenv("EMAIL_CC", "")  # e.g. manager@yourcompany.com — set in .env
MIN_DAYS_OPEN = 45
TOP_N      = 15  # rows shown in the email table


def browse_url(key):
    """Build a browser-friendly Jira issue URL from a ticket key, e.g. IT-12345."""
    base = JIRA_BASE.split("/rest/")[0].rstrip("/")
    return f"{base}/browse/{key}"


def parse_int(val, default=0):
    """Safely cast a value to int, returning default on failure."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def load_tickets():
    """
    Load all ticket rows from jira_report.csv.

    Returns:
        List of ticket dicts with typed fields (numeric columns cast to int).
    """
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        return [
            {
                "ticket_key":          r.get("ticket_key", ""),
                "summary":             r.get("summary", ""),
                "assignee":            r.get("assignee") or "Unassigned",
                "status":              r.get("status") or "Unknown",
                "priority":            r.get("priority") or "None",
                "created_date":        r.get("created_date", ""),
                "days_open":           parse_int(r.get("days_open")),
                "last_response_date":  r.get("last_response_date", ""),
                "days_since_response": parse_int(r.get("days_since_response")),
                "times_flagged":       parse_int(r.get("times_flagged")),
            }
            for r in csv.DictReader(f)
        ]


def load_metadata():
    """
    Load run metadata from jira_report_metadata.json.
    Returns an empty dict if the file is missing or contains invalid JSON.
    """
    if not os.path.exists(META_PATH):
        return {}
    with open(META_PATH, encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def _cell(text, bold=False, color=""):
    """
    Render a <td> element with inline styles safe for Outlook's rendering engine.

    Uses only inline CSS — no CSS grid, flexbox, or external stylesheets — because
    Outlook strips most non-inline styles and ignores modern layout properties.
    """
    style = "padding:8px 12px;border-bottom:1px solid #e5e7eb;font-size:13px;"
    if color:
        style += f"color:{color};"
    if bold:
        return f'<td style="{style}font-weight:600;">{text}</td>'
    return f'<td style="{style}">{text}</td>'


def build_html(tickets, metadata):
    """
    Compose the full HTML email body from ticket data.

    Email sections:
      - Blue header banner with report title and generated date.
      - Green confirmation banner (raw fetched → active after filtering).
      - Four KPI stat cards (table-based layout for Outlook compatibility).
      - Top 5 assignees ranked by ticket count.
      - Top N longest-open tickets table; days-since-response highlighted red
        when >= MIN_DAYS_OPEN with no update.

    Args:
        tickets:  List of ticket dicts from load_tickets().
        metadata: Dict from load_metadata() supplying page/total/date context.

    Returns:
        Complete HTML string ready to assign to mail.HTMLBody in Outlook.
    """
    total         = len(tickets)
    avg_days      = round(sum(t["days_open"] for t in tickets) / total, 1) if total else 0
    stale         = sum(1 for t in tickets if t["days_since_response"] >= MIN_DAYS_OPEN)
    unassigned    = sum(1 for t in tickets if t["assignee"] == "Unassigned")
    top_tickets   = sorted(tickets, key=lambda t: t["days_open"], reverse=True)[:TOP_N]
    assignee_dist = Counter(t["assignee"] for t in tickets).most_common(5)

    gen_date  = metadata.get("generated_at", "")[:10] or datetime.now().strftime("%Y-%m-%d")
    pages     = metadata.get("pages_fetched", "?")
    raw_total = metadata.get("total_fetched", "?")
    jira_host = JIRA_BASE.split("/rest/")[0].rstrip("/").replace("https://", "").replace("http://", "")

    # --- stat cards (table-based for email safety) ---
    def stat_card(value, label, warn=False):
        val_color = "#dc2626" if warn else "#111827"
        return f"""
        <td style="width:25%;padding:0 8px;">
          <table width="100%" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;">
            <tr><td style="padding:16px 18px;">
              <div style="font-size:26px;font-weight:700;color:{val_color};">{value}</div>
              <div style="font-size:12px;color:#6b7280;margin-top:4px;">{label}</div>
            </td></tr>
          </table>
        </td>"""

    stat_row = f"""
    <table width="100%" cellpadding="0" cellspacing="0" style="margin:20px 0;">
      <tr>
        {stat_card(total, "Active tickets in scope")}
        {stat_card(avg_days, "Avg days open")}
        {stat_card(stale, f"No response {MIN_DAYS_OPEN}+ days", warn=True)}
        {stat_card(unassigned, "Unassigned tickets", warn=True)}
      </tr>
    </table>"""

    # --- top assignees ---
    assignee_rows = "".join(
        f'<tr><td style="padding:5px 0;font-size:13px;color:#374151;">{html.escape(name)}</td>'
        f'<td style="padding:5px 0 5px 12px;font-size:13px;font-weight:600;color:#111827;">{count}</td></tr>'
        for name, count in assignee_dist
    )

    # --- top tickets table ---
    ticket_rows = ""
    for t in top_tickets:
        key     = html.escape(t["ticket_key"])
        summary = html.escape(t["summary"])
        # Escape for the href attribute context too — the ticket key flows into
        # the URL, so quote it to prevent attribute-breakout / injection.
        link    = html.escape(browse_url(t["ticket_key"]), quote=True)
        days_r  = t["days_since_response"]
        days_o  = t["days_open"]
        resp_color = "#dc2626" if days_r >= MIN_DAYS_OPEN else "#374151"

        ticket_rows += (
            f"<tr>"
            + _cell(f'<a href="{link}" style="color:#2563eb;text-decoration:none;font-weight:500;">{key}</a>')
            + _cell(summary)
            + _cell(html.escape(t["assignee"]))
            + _cell(html.escape(t["status"]))
            + _cell(str(days_o))
            + _cell(f'<span style="color:{resp_color};font-weight:600;">{days_r}</span>')
            + "</tr>"
        )

    th_style = "padding:8px 12px;background:#f9fafb;font-size:12px;font-weight:600;color:#374151;text-align:left;border-bottom:2px solid #e5e7eb;"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:32px 0;">
<tr><td align="center">
<table width="700" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;">

  <!-- Header -->
  <tr><td style="background:#1e40af;padding:28px 32px;">
    <div style="font-size:22px;font-weight:700;color:#ffffff;">Jira IT Open Ticket Report</div>
    <div style="font-size:13px;color:#bfdbfe;margin-top:6px;">
      Active unresolved tickets older than {MIN_DAYS_OPEN} days &mdash; generated {gen_date}
    </div>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:28px 32px;">

    <!-- Confirmation banner -->
    <table width="100%" cellpadding="0" cellspacing="0" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;margin-bottom:20px;">
      <tr><td style="padding:12px 16px;font-size:13px;color:#166534;">
        Fetched <strong>{raw_total}</strong> raw tickets across <strong>{pages}</strong> pages
        &rarr; <strong>{total}</strong> active tickets after filtering.
      </td></tr>
    </table>

    <!-- Stat cards -->
    {stat_row}

    <!-- Top assignees -->
    <div style="font-size:15px;font-weight:600;color:#111827;margin:24px 0 10px;">Top 5 Assignees by Ticket Count</div>
    <table cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
      {assignee_rows}
    </table>

    <!-- Top tickets -->
    <div style="font-size:15px;font-weight:600;color:#111827;margin:0 0 10px;">Top {TOP_N} Longest Open Tickets</div>
    <div style="font-size:12px;color:#6b7280;margin-bottom:10px;">
      Days since response highlighted in red when {MIN_DAYS_OPEN}+ days with no update.
    </div>
    <table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden;">
      <thead>
        <tr>
          <th style="{th_style}">Ticket</th>
          <th style="{th_style}">Summary</th>
          <th style="{th_style}">Assignee</th>
          <th style="{th_style}">Status</th>
          <th style="{th_style}">Days Open</th>
          <th style="{th_style}">Days Since Response</th>
        </tr>
      </thead>
      <tbody>{ticket_rows}</tbody>
    </table>

  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:16px 32px;">
    <div style="font-size:12px;color:#9ca3af;">
      Generated by JiraReporter &bull; {jira_host} &bull; {gen_date}
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def send_via_outlook(subject, html_body, to_addr, cc_addr=""):
    """
    Send an HTML email using the locally installed Outlook app via Windows COM automation.

    Requires Outlook to be installed and the user to be logged in — no SMTP credentials
    are needed. The email sends from whichever account is set as default in Outlook.
    This is why the Task Scheduler job is configured for interactive (logged-in) sessions only.

    Args:
        subject:   Email subject line string.
        html_body: Full HTML string for the email body.
        to_addr:   Recipient address or semicolon-separated list of addresses.
        cc_addr:   Optional CC address or semicolon-separated list (omitted if empty).
    """
    try:
        import win32com.client as win32
    except ImportError:
        sys.exit("pywin32 is not installed. Run: pip install pywin32")

    outlook = win32.Dispatch("outlook.application")
    mail    = outlook.CreateItem(0)  # 0 = olMailItem
    mail.To      = to_addr
    mail.Subject = subject
    if cc_addr:
        mail.CC = cc_addr
    mail.HTMLBody = html_body
    mail.Send()
    print(f"Email sent to: {to_addr}" + (f" (cc: {cc_addr})" if cc_addr else ""))


if __name__ == "__main__":
    if not EMAIL_TO:
        sys.exit("Set EMAIL_TO in your .env file before running.")

    if not os.path.exists(CSV_PATH):
        sys.exit(f"{CSV_PATH} not found — run jira_fetcher.py first.")

    tickets  = load_tickets()
    metadata = load_metadata()

    if not tickets:
        sys.exit("No tickets in CSV — nothing to send.")

    gen_date = (metadata.get("generated_at") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    subject  = f"Jira IT Open Tickets — {gen_date} ({len(tickets)} active)"

    html_body = build_html(tickets, metadata)
    send_via_outlook(subject, html_body, EMAIL_TO, EMAIL_CC)
