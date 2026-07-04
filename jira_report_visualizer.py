"""
jira_report_visualizer.py — HTML Dashboard Generator

Reads jira_report.csv and jira_report_metadata.json produced by jira_fetcher.py
and outputs a self-contained, interactive HTML dashboard (jira_report.html).

All external dependencies (Chart.js) are bundled inline so the dashboard works
inside SharePoint document libraries without CDN access.
"""

import argparse
import csv
import html
import json
import os
import urllib.parse
from collections import Counter
from datetime import date as _date

MIN_DAYS_OPEN = 45
CHARTJS_PATH  = os.path.join(os.path.dirname(__file__), "chartjs.min.js")

RESOLVED_STATUSES = {
    "done", "completed", "fulfilled", "canceled", "cancelled",
    "closed", "resolved", "won't do", "duplicate", "approved"
}


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_jira_url(url):
    if not url:
        return "https://yourcompany.atlassian.net"  # placeholder default — set JIRA_BASE_URL in .env
    return url.split("/rest/")[0].rstrip("/")


def fmt_date(iso):
    """Return YYYY-MM-DD from an ISO date string, or blank."""
    return (iso or "")[:10]


def load_tickets(csv_path):
    tickets = []
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            status = row.get("status", "") or ""
            if status.strip().lower() in RESOLVED_STATUSES:
                skipped += 1
                continue
            tickets.append({
                "ticket_key":          row.get("ticket_key", ""),
                "summary":             row.get("summary", ""),
                "assignee":            row.get("assignee", "Unassigned") or "Unassigned",
                "reporter":            row.get("reporter", "Unknown") or "Unknown",
                "status":              status or "Unknown",
                "priority":            row.get("priority", "None") or "None",
                "created_date":        fmt_date(row.get("created_date", "")),
                "days_open":           parse_int(row.get("days_open", 0)),
                "last_response_date":  row.get("last_response_date", ""),
                "days_since_response": parse_int(row.get("days_since_response", 0)),
                "times_flagged":       parse_int(row.get("times_flagged", 0)),
            })
    if skipped:
        print(f"  (visualizer filtered out {skipped} resolved/completed tickets from CSV)")
    return tickets


def load_approaching(csv_path="jira_approaching.csv"):
    if not os.path.exists(csv_path):
        return []
    tickets = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            status = row.get("status", "") or ""
            if status.strip().lower() in RESOLVED_STATUSES:
                continue
            tickets.append({
                "ticket_key":    row.get("ticket_key", ""),
                "summary":       row.get("summary", ""),
                "assignee":      row.get("assignee", "Unassigned") or "Unassigned",
                "status":        status or "Unknown",
                "priority":      row.get("priority", "None") or "None",
                "created_date":  fmt_date(row.get("created_date", "")),
                "days_open":     parse_int(row.get("days_open", 0)),
                "days_until_45": parse_int(row.get("days_until_45", 0)),
            })
    tickets.sort(key=lambda t: t["days_until_45"])
    return tickets


def load_all_tickets(all_csv_path, enriched_tickets):
    """Return list of all open tickets merged with enriched 45+ day data."""
    if not os.path.exists(all_csv_path):
        return None
    enriched_map = {t["ticket_key"]: t for t in enriched_tickets}
    today = _date.today()
    tickets = []
    with open(all_csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            status = row.get("status", "") or ""
            if status.strip().lower() in RESOLVED_STATUSES:
                continue
            key = row.get("ticket_key", "")
            if key in enriched_map:
                tickets.append(enriched_map[key])
            else:
                created_str = fmt_date(row.get("created_date", ""))
                days_open = 0
                if created_str:
                    try:
                        created_dt = _date.fromisoformat(created_str)
                        days_open = (today - created_dt).days
                    except ValueError:
                        pass
                tickets.append({
                    "ticket_key":          key,
                    "summary":             row.get("summary", ""),
                    "assignee":            row.get("assignee", "Unassigned") or "Unassigned",
                    "reporter":            row.get("reporter", "Unknown") or "Unknown",
                    "status":              status or "Unknown",
                    "priority":            row.get("priority", "None") or "None",
                    "created_date":        created_str,
                    "days_open":           days_open,
                    "last_response_date":  "",
                    "days_since_response": days_open,
                    "times_flagged":       0,
                })
    return tickets


def load_metadata(meta_path="jira_report_metadata.json"):
    if not os.path.exists(meta_path):
        return {}
    with open(meta_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}


def load_chartjs():
    if os.path.exists(CHARTJS_PATH):
        with open(CHARTJS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    return "console.warn('Chart.js not found — charts disabled.');"


def _status_class(status):
    key = status.strip().lower()
    if "waiting" in key:     return "bd-waiting"
    if "in progress" in key: return "bd-progress"
    if "development" in key: return "bd-develop"
    if "validation" in key:  return "bd-valid"
    if "discovery" in key:   return "bd-discovery"
    if "hold" in key:        return "bd-hold"
    if "pending" in key:     return "bd-hold"
    if key in ("completed", "done", "fulfilled"):                           return "bd-done"
    if key in ("canceled", "cancelled", "closed", "resolved", "won't do",
               "duplicate", "approved"):                                    return "bd-closed"
    if key == "open":        return "bd-open"
    return "bd-neutral"


def _status_badge(status):
    return (
        f'<span class="badge {_status_class(status)}">'
        f'{html.escape(status)}</span>'
    )


def _priority_badge(priority):
    key = priority.strip().lower()
    if key == "high":  cls = "bd-high"
    elif key == "low": cls = "bd-low"
    else:              cls = "bd-medium"
    return f'<span class="badge {cls}">{html.escape(priority)}</span>'


def make_html_report(tickets, output_path, browser_base_url, metadata=None, approaching=None, all_tickets=None):
    metadata    = metadata or {}
    approaching = approaching or []
    total       = len(tickets)
    avg_days    = round(sum(t["days_open"] for t in tickets) / total, 1) if total else 0
    unassigned  = sum(1 for t in tickets if t["assignee"] == "Unassigned")
    gen_date    = (metadata.get("generated_at") or "")[:10]
    pages       = metadata.get("pages_fetched", "?")
    raw_total   = metadata.get("total_fetched", "?")
    cutoff      = (metadata.get("cutoff_date") or "")[:10]
    total_all   = metadata.get("total_all_statuses", None)
    approaching_window = metadata.get("approaching_window", 7)

    assignee_counts = Counter(t["assignee"] for t in tickets)
    status_counts   = Counter(t["status"]   for t in tickets)
    stale_tickets   = [t for t in tickets if t["days_since_response"] >= MIN_DAYS_OPEN]
    flagged         = sorted(
        [t for t in tickets if t["times_flagged"] >= 2],
        key=lambda t: (t["times_flagged"], t["days_since_response"]),
        reverse=True
    )

    # Age buckets
    age_buckets = {"45-60d": 0, "60-90d": 0, "90-180d": 0, "180d+": 0}
    for t in tickets:
        d = t["days_open"]
        if d < 60:    age_buckets["45-60d"]  += 1
        elif d < 90:  age_buckets["60-90d"]  += 1
        elif d < 180: age_buckets["90-180d"] += 1
        else:         age_buckets["180d+"]   += 1

    assignee_leaderboard = sorted(assignee_counts.items(), key=lambda x: x[1], reverse=True)
    max_assignee_count   = assignee_leaderboard[0][1] if assignee_leaderboard else 1
    status_list          = sorted(status_counts.items(), key=lambda x: x[1], reverse=True)
    max_status_count     = status_list[0][1] if status_list else 1

    chartjs_inline = load_chartjs()

    def browse(key):
        return f"{browser_base_url}/browse/{key}"

    TH = (
        'style="padding:11px 14px;background:var(--th-bg);font-size:0.72rem;font-weight:600;'
        'color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;'
        'border-bottom:1px solid var(--border);white-space:nowrap;text-align:left;"'
    )
    TD     = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);"'
    ACT_TH = ('class="act-col" style="padding:11px 14px;background:var(--th-bg);font-size:0.72rem;'
              'font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;'
              'border-bottom:1px solid var(--border);white-space:nowrap;text-align:center;"')
    ACT_TD = 'class="act-col" style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;position:relative;"'
    TH_C   = ('style="padding:11px 14px;background:var(--th-bg);font-size:0.72rem;font-weight:600;'
              'color:var(--text-muted);text-transform:uppercase;letter-spacing:0.06em;'
              'border-bottom:1px solid var(--border);white-space:nowrap;text-align:center;"')
    TD_C   = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;"'
    TD_SUM = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"'

    def days_cell(n, warn=MIN_DAYS_OPEN):
        color = "var(--red)" if n >= warn else "var(--text-muted)"
        return f'<td {TD_C}><span style="color:{color};font-weight:600;">{n}</span></td>'

    def ra(t):
        return f'data-assignee="{html.escape(t["assignee"])}"'

    # ── Flagged table ──
    flagged_body = ""
    if flagged:
        flagged_rows = ""
        for t in flagged:
            k   = html.escape(t["ticket_key"])
            url = browse(t["ticket_key"])
            first_name = t['assignee'].split()[0] if t['assignee'] and t['assignee'] != 'Unassigned' else t['assignee']
            mailto_subject = f"Follow-up Required: [{t['ticket_key']}] {t['summary'][:60]}"
            mailto_body = (
                f"Hi {first_name},\r\n\r\n"
                f"This is a follow-up regarding ticket {t['ticket_key']}: \"{t['summary']}\".\r\n\r\n"
                f"This ticket has been open for {t['days_open']} days without resolution. "
                f"Could you please provide a status update?\r\n\r\n"
                f"Ticket link: {url}\r\n\r\n"
                f"Thank you,\r\n"
                f"IT Management"
            )
            mailto = f"mailto:?subject={urllib.parse.quote(mailto_subject)}&body={urllib.parse.quote(mailto_body)}"
            flagged_rows += f"""<tr {ra(t)} data-key="{k}" data-url="{url}" data-status="{html.escape(t['status'])}" data-summary="{html.escape(t['summary'], quote=True)}" data-created="{t['created_date']}" data-days="{t['days_open']}">
              <td {TD}><a href="{url}" target="_blank" class="ticket-link">{k}</a></td>
              <td {TD_SUM}>{html.escape(t["summary"])}</td>
              <td {TD}>{html.escape(t["assignee"])}</td>
              <td {TD}>{html.escape(t["reporter"])}</td>
              <td {TD}>{t["created_date"] or "—"}</td>
              <td {TD}>{_status_badge(t["status"])}</td>
              <td {TD_C}><span style="color:var(--red);font-weight:700;">{t["times_flagged"]}</span></td>
              {days_cell(t["days_open"], 60)}
              {days_cell(t["days_since_response"])}
              <td {ACT_TD}>
                <button class="menu-btn" onclick="toggleMenu(this)" title="More actions">&#8943;</button>
                <div class="action-menu">
                  <a class="menu-item" href="{url}" target="_blank">&#x1F517; View in Jira</a>
                  <button class="menu-item" onclick="copyLink(this)">&#x1F4CB; Copy Link</button>
                  <a class="menu-item" href="{mailto}">&#x2709; Send Follow-up Draft</a>
                  <button class="menu-item" onclick="openCommentPanel(this,'{k}')">&#x1F4AC; Add Comment</button>
                  <button class="menu-item" onclick="toggleReviewed(this)">&#x2713; Mark as Reviewed</button>
                  <button class="menu-item" onclick="copyTicketSummary(this)">&#x1F4DD; Copy Summary</button>
                </div>
              </td>
            </tr>"""
        flagged_body = f"""<table id="tbl-flagged" style="width:100%;border-collapse:collapse;table-layout:fixed;min-width:900px;">
          <colgroup>
            <col style="width:85px"><col style="width:190px"><col style="width:130px">
            <col style="width:115px"><col style="width:90px"><col style="width:130px">
            <col style="width:70px"><col style="width:90px"><col style="width:75px">
            <col style="width:80px">
          </colgroup>
          <thead><tr>
            <th {TH}>Ticket</th><th {TH}>Summary</th><th {TH}>Assignee</th>
            <th {TH}>Reporter</th><th {TH}>Created</th><th {TH}>Status</th>
            <th {TH_C}>Reports</th>
            <th {TH_C}>Days Open</th><th {TH_C}>No Reply</th>
            <th {ACT_TH}>Actions</th>
          </tr></thead><tbody>{flagged_rows}</tbody></table>"""
    else:
        flagged_body = '<div class="empty-state">No flagged tickets found — all clear.</div>'

    # ── Approaching table ──
    if approaching:
        approaching_rows = ""
        for t in approaching:
            k = html.escape(t["ticket_key"])
            d = t["days_until_45"]
            urgency = "var(--red)" if d <= 2 else "var(--amber)"
            approaching_rows += f"""<tr data-assignee="{html.escape(t["assignee"])}" data-status="{html.escape(t["status"])}">
              <td {TD}><a href="{browse(t['ticket_key'])}" target="_blank" class="ticket-link">{k}</a></td>
              <td {TD_SUM}>{html.escape(t["summary"])}</td>
              <td {TD}>{html.escape(t["assignee"])}</td>
              <td {TD}>{_status_badge(t["status"])}</td>
              <td {TD}>{t["created_date"] or "—"}</td>
              <td {TD}><span style="color:var(--text-muted);font-weight:600;">{t["days_open"]}</span></td>
              <td {TD}><span style="color:{urgency};font-weight:700;">{d} day{"s" if d != 1 else ""}</span></td>
            </tr>"""
        approaching_body = f"""<table id="tbl-approaching" style="width:100%;border-collapse:collapse;min-width:700px;">
          <thead><tr>
            <th {TH}>Ticket</th><th {TH}>Summary</th><th {TH}>Assignee</th>
            <th {TH}>Status</th><th {TH}>Created</th>
            <th {TH}>Days Open</th><th {TH}>Days Left</th>
          </tr></thead><tbody>{approaching_rows}</tbody></table>"""
    else:
        approaching_body = (
            f'<div class="empty-state">No tickets approaching the {MIN_DAYS_OPEN}-day threshold '
            f'within the next {approaching_window} days.</div>'
        )

    # ── Grand total banner ──
    total_all_html = ""
    if total_all is not None:
        total_all_html = f"""
  <div class="total-banner">
    <div>
      <div class="banner-label">Total Unresolved IT Tickets</div>
      <div class="banner-num">{total_all:,}</div>
      <div style="font-size:0.78rem;color:var(--text-muted);margin-top:6px;">
        As of {gen_date} &bull; refreshed every scheduled run
      </div>
    </div>
    <div style="display:flex;gap:24px;flex-wrap:wrap;">
      <div style="text-align:center;">
        <div class="banner-colored-num" style="font-size:1.5rem;font-weight:700;color:#a78bfa;">{total_all - total:,}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">Unresolved &lt; 45d</div>
      </div>
      <div class="vdivider"></div>
      <div style="text-align:center;">
        <div class="banner-colored-num" style="font-size:1.5rem;font-weight:700;color:var(--blue);">{total:,}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">Unresolved 45d+</div>
      </div>
      <div class="vdivider"></div>
      <div style="text-align:center;">
        <div class="banner-colored-num" style="font-size:1.5rem;font-weight:700;color:var(--amber);">{len(approaching):,}</div>
        <div style="font-size:0.75rem;color:var(--text-muted);margin-top:4px;">Approaching 45d</div>
      </div>
    </div>
  </div>"""

    # ── Status breakdown ──
    status_breakdown_html = ""
    for status, count in status_list:
        pct   = round(count / max_status_count * 100)
        badge = _status_badge(status)
        pct_l = round(count / total * 100) if total else 0
        status_breakdown_html += f"""
      <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
          {badge}
          <span style="font-size:0.82rem;font-weight:600;color:var(--text-primary);">{count}
            <span style="color:var(--text-muted);font-weight:400;">({pct_l}%)</span></span>
        </div>
        <div style="height:4px;background:var(--border);border-radius:2px;">
          <div style="height:4px;background:var(--blue);border-radius:2px;width:{pct}%;"></div>
        </div>
      </div>"""

    # ── Ticket JSON for dynamic top-10 ──
    tickets_json = json.dumps([{
        "key":      t["ticket_key"],
        "summary":  t["summary"],
        "assignee": t["assignee"],
        "reporter": t["reporter"],
        "created":  t["created_date"],
        "status":   t["status"],
        "priority": t["priority"],
        "days":     t["days_open"],
        "response": t["days_since_response"],
        "flagged":  t["times_flagged"],
        "url":      browse(t["ticket_key"]),
    } for t in tickets])
    tickets_json = tickets_json.replace('</', '<\\/')

    has_all = all_tickets is not None and len(all_tickets) > 0
    if has_all:
        all_tickets_json = json.dumps([{
            "key":      t["ticket_key"],
            "summary":  t["summary"],
            "assignee": t["assignee"],
            "reporter": t["reporter"],
            "created":  t["created_date"],
            "status":   t["status"],
            "priority": t["priority"],
            "days":     t["days_open"],
            "response": t["days_since_response"],
            "flagged":  t["times_flagged"],
            "url":      browse(t["ticket_key"]),
        } for t in all_tickets])
        all_tickets_json = all_tickets_json.replace('</', '<\\/')
    else:
        all_tickets_json = "[]"

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>IT Open Ticket Dashboard</title>
  <style>
    /* ── CSS Variables — dark mode (default) ── */
    :root {{
      --bg:          #0f1117;
      --bg-card:     #161b27;
      --bg-th:       #1e2433;
      --text-primary:#f1f5f9;
      --text-muted:  #64748b;
      --border:      rgba(255,255,255,0.07);
      --border-soft: rgba(255,255,255,0.04);
      --blue:        #60a5fa;
      --teal:        #2dd4bf;
      --amber:       #fbbf24;
      --red:         #f87171;
      --purple:      #a78bfa;
      --th-bg:       #1e2433;
      --hover-row:   rgba(255,255,255,0.025);
      --sb-active-bg:rgba(96,165,250,0.15);
      --sb-active-c: #60a5fa;
      --sb-active-bd:rgba(96,165,250,0.3);
      --input-bg:    rgba(255,255,255,0.05);
      --input-bd:    rgba(255,255,255,0.1);
      --menu-bg:     #1e2433;
    }}
    /* ── Light mode overrides ── */
    html.light {{
      --bg:          #f1f5f9;
      --bg-card:     #ffffff;
      --bg-th:       #f8fafc;
      --text-primary:#0f172a;
      --text-muted:  #64748b;
      --border:      rgba(0,0,0,0.09);
      --border-soft: rgba(0,0,0,0.05);
      --th-bg:       #f8fafc;
      --hover-row:   rgba(0,0,0,0.02);
      --sb-active-bg:rgba(37,99,235,0.08);
      --sb-active-c: #2563eb;
      --sb-active-bd:rgba(37,99,235,0.25);
      --input-bg:    rgba(0,0,0,0.04);
      --input-bd:    rgba(0,0,0,0.12);
      --menu-bg:     #ffffff;
    }}

    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: var(--bg);
      color: var(--text-primary);
      -webkit-font-smoothing: antialiased;
      transition: background 0.2s, color 0.2s;
    }}
    .page {{ max-width: 1600px; margin: 0 auto; padding: 28px 32px; }}

    /* ── Header ── */
    .header {{
      display: flex; justify-content: space-between; align-items: flex-start;
      padding-bottom: 20px; border-bottom: 1px solid var(--border);
      margin-bottom: 24px; flex-wrap: wrap; gap: 12px;
    }}
    .header h1 {{ margin: 0; font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; }}
    .header .sub {{ font-size: 0.8rem; color: var(--text-muted); margin-top: 4px; }}
    .header .right {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .pill {{
      background: rgba(96,165,250,0.12); color: var(--blue);
      border: 1px solid rgba(96,165,250,0.25); padding: 5px 14px;
      border-radius: 999px; font-size: 0.75rem; font-weight: 600; white-space: nowrap;
    }}
    .gen-time {{ font-size: 0.8rem; color: var(--text-muted); }}

    /* ── Theme toggle ── */
    .theme-toggle {{
      background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 999px; padding: 5px 12px; cursor: pointer;
      font-size: 0.78rem; font-weight: 600; color: var(--text-muted);
      font-family: inherit; transition: all 0.15s;
    }}
    .theme-toggle:hover {{ color: var(--text-primary); border-color: var(--blue); }}

    /* ── View toggle ── */
    .view-toggle {{
      display: inline-flex; background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 999px; padding: 3px; gap: 2px;
    }}
    .vt-btn {{
      background: transparent; border: none; border-radius: 999px;
      padding: 4px 14px; font-size: 0.75rem; font-weight: 600;
      color: var(--text-muted); cursor: pointer; font-family: inherit;
      transition: all 0.15s; white-space: nowrap;
    }}
    .vt-btn:hover {{ color: var(--text-primary); }}
    .vt-btn.active {{ background: var(--blue); color: #0f1117; }}
    html.light .vt-btn.active {{ color: #fff; }}

    /* ── Grand total banner ── */
    .total-banner {{
      background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px;
      padding: 20px 28px; margin-bottom: 20px;
      display: flex; align-items: center; gap: 32px; flex-wrap: wrap;
    }}
    .banner-label {{
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 6px;
    }}
    .banner-num {{ font-size: 3rem; font-weight: 800; color: var(--text-primary); letter-spacing: -0.04em; line-height: 1; }}
    .vdivider {{ width: 1px; background: var(--border); align-self: stretch; }}

    /* ── Confirm banner ── */
    .fetch-banner {{
      background: rgba(45,212,191,0.11); border: 1px solid rgba(45,212,191,0.28);
      border-radius: 10px; padding: 12px 18px; font-size: 0.8rem;
      color: #2dd4bf; margin-bottom: 22px;
    }}
    .fetch-banner strong {{ color: #14b8a6; }}
    html.light .fetch-banner {{
      background: rgba(20,184,166,0.09); border-color: rgba(20,184,166,0.25);
      color: #0f766e;
    }}
    html.light .fetch-banner strong {{ color: #0d9488; }}

    /* ── Layout ── */
    .layout {{ display: flex; gap: 20px; align-items: flex-start; }}

    /* ── Sidebar ── */
    .sidebar {{
      width: 240px; flex-shrink: 0; position: sticky; top: 20px;
      max-height: calc(100vh - 40px); overflow-y: auto;
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 14px; padding: 18px 14px;
      scrollbar-width: thin; scrollbar-color: var(--border) transparent;
    }}
    .sidebar::-webkit-scrollbar {{ width: 4px; }}
    .sidebar::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 2px; }}
    .sb-title {{
      font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 10px;
    }}
    .sb-search {{
      width: 100%; background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 8px; padding: 7px 10px; color: var(--text-primary);
      font-size: 0.82rem; font-family: inherit; outline: none; margin-bottom: 8px;
    }}
    .sb-search:focus {{ border-color: rgba(96,165,250,0.5); }}
    .sb-search::placeholder {{ color: var(--text-muted); }}
    .sb-all {{
      width: 100%; background: rgba(96,165,250,0.12);
      border: 1px solid rgba(96,165,250,0.25); border-radius: 8px;
      color: var(--blue); font-size: 0.8rem; font-weight: 600;
      padding: 7px 10px; cursor: pointer; font-family: inherit;
      text-align: left; margin-bottom: 10px; transition: background 0.15s;
    }}
    .sb-all:hover {{ background: rgba(96,165,250,0.2); }}
    .sb-all.active {{ background: var(--blue); color: #0f1117; }}
    .sb-divider {{ height: 1px; background: var(--border); margin: 12px 0; }}
    .sb-item {{ margin-bottom: 6px; }}
    .assignee-btn {{
      width: 100%; background: transparent; border: 1px solid transparent;
      border-radius: 7px; color: var(--text-muted); font-size: 0.8rem;
      font-family: inherit; padding: 5px 8px; cursor: pointer;
      display: flex; justify-content: space-between; align-items: center;
      text-align: left; transition: all 0.15s;
    }}
    .assignee-btn:hover {{ background: var(--hover-row); color: var(--text-primary); border-color: var(--border); }}
    .assignee-btn.active {{ background: var(--sb-active-bg); color: var(--sb-active-c); border-color: var(--sb-active-bd); }}
    .sb-name {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }}
    .sb-count {{
      font-size: 0.72rem; font-weight: 700; color: var(--text-muted);
      background: var(--border); border-radius: 999px; padding: 1px 6px;
      margin-left: 6px; flex-shrink: 0;
    }}
    .assignee-btn.active .sb-count {{ background: var(--sb-active-bg); color: var(--sb-active-c); }}
    .sb-bar {{ height: 2px; background: var(--border); border-radius: 1px; margin-top: 3px; margin-left: 8px; }}
    .sb-bar-fill {{ height: 2px; background: rgba(96,165,250,0.4); border-radius: 1px; }}
    .assignee-btn.active + .sb-bar .sb-bar-fill {{ background: var(--blue); }}
    .export-all-btn {{
      width: 100%; margin-top: 4px;
      background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 8px; color: var(--text-muted); font-size: 0.78rem; font-weight: 600;
      padding: 7px 10px; cursor: pointer; font-family: inherit; transition: all 0.15s;
    }}
    .export-all-btn:hover {{ color: var(--blue); border-color: var(--sb-active-bd); }}

    /* ── Filter indicator ── */
    .filter-indicator {{
      display: none; background: rgba(96,165,250,0.08);
      border: 1px solid rgba(96,165,250,0.2); border-radius: 8px;
      padding: 8px 14px; font-size: 0.82rem; color: var(--blue);
      margin-bottom: 16px; align-items: center; gap: 10px;
    }}
    .filter-indicator.visible {{ display: flex; }}
    .fi-clear {{
      margin-left: auto; background: none; border: none; color: var(--blue);
      font-size: 0.78rem; cursor: pointer; font-family: inherit; text-decoration: underline;
    }}

    /* ── Stat cards ── */
    .cards {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 20px; }}
    .card {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 22px 24px; }}
    .card .num {{ font-size: 2.6rem; font-weight: 800; line-height: 1; letter-spacing: -0.03em; }}
    .card .lbl {{ font-size: 0.78rem; color: var(--text-muted); margin-top: 8px; font-weight: 500; }}
    .card.blue  .num {{ color: var(--blue); }}
    .card.teal  .num {{ color: var(--teal); }}
    .card.amber .num {{ color: var(--amber); }}
    .card.red   .num {{ color: var(--red); }}

    /* ── Charts ── */
    .chart-row-2col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
    .chart-row {{ display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-bottom: 24px; }}
    .chart-box {{ background: var(--bg-card); border: 1px solid var(--border); border-radius: 14px; padding: 22px 24px; }}
    .chart-label {{
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase;
      letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: 16px;
    }}

    /* ── Section headers ── */
    .section-hd {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }}
    .section-hd h2 {{ margin: 0; font-size: 0.95rem; font-weight: 700; }}
    .section-hd .count {{
      font-size: 0.75rem; color: var(--text-muted);
      background: var(--border); padding: 2px 8px; border-radius: 999px;
    }}
    .section-sub {{ font-size: 0.78rem; color: var(--text-muted); margin: -4px 0 12px; }}
    .sort-btns {{ display: flex; gap: 4px; margin-left: 2px; }}
    .sort-btn {{
      font-size: 0.72rem; font-weight: 600; padding: 2px 9px; border-radius: 6px; cursor: pointer;
      border: 1px solid var(--border); background: var(--bg-card); color: var(--text-muted);
      transition: all 0.15s; font-family: inherit;
    }}
    .sort-btn:hover {{ border-color: var(--blue); color: var(--blue); }}
    .sort-btn.active {{ background: var(--blue); color: #fff; border-color: var(--blue); }}

    /* ── Tables ── */
    .table-wrap {{
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 14px; overflow: clip; margin-bottom: 28px;
    }}
    .table-scroll {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; min-width: 700px; }}
    tr:hover td {{ background: var(--hover-row); }}
    tr:last-child td {{ border-bottom: none !important; }}
    .ticket-link {{ color: var(--blue); font-weight: 600; text-decoration: none; }}
    .ticket-link:hover {{ text-decoration: underline; }}
    .badge {{
      display: inline-block; padding: 2px 10px; border-radius: 999px;
      font-size: 0.73rem; font-weight: 600; letter-spacing: 0.02em;
      border: 1.5px solid rgba(0,0,0,0.45);
    }}
    /* Badge colour classes — light-mode defaults (high contrast on white) */
    .bd-waiting  {{ color:#b45309; background:rgba(180,83,9,0.10); }}
    .bd-progress {{ color:#4338ca; background:rgba(67,56,202,0.10); }}
    .bd-develop  {{ color:#7e22ce; background:rgba(126,34,206,0.10); }}
    .bd-valid    {{ color:#6d28d9; background:rgba(109,40,217,0.10); }}
    .bd-discovery{{ color:#0e7490; background:rgba(14,116,158,0.10); }}
    .bd-hold     {{ color:#475569; background:rgba(71,85,105,0.10); }}
    .bd-done     {{ color:#065f46; background:rgba(6,95,70,0.10); }}
    .bd-closed   {{ color:#374151; background:rgba(55,65,81,0.10); }}
    .bd-open     {{ color:#1d4ed8; background:rgba(29,78,216,0.10); }}
    .bd-neutral  {{ color:#475569; background:rgba(71,85,105,0.10); }}
    .bd-high     {{ color:#b91c1c; background:rgba(185,28,28,0.10); }}
    .bd-medium   {{ color:#1d4ed8; background:rgba(29,78,216,0.10); }}
    .bd-low      {{ color:#475569; background:rgba(71,85,105,0.10); }}
    /* Dark-mode badge overrides */
    html:not(.light) .bd-waiting  {{ color:#fbbf24; background:rgba(251,191,36,0.18); }}
    html:not(.light) .bd-progress {{ color:#818cf8; background:rgba(129,140,248,0.18); }}
    html:not(.light) .bd-develop  {{ color:#c084fc; background:rgba(192,132,252,0.18); }}
    html:not(.light) .bd-valid    {{ color:#a78bfa; background:rgba(167,139,250,0.18); }}
    html:not(.light) .bd-discovery{{ color:#22d3ee; background:rgba(34,211,238,0.15); }}
    html:not(.light) .bd-hold     {{ color:#94a3b8; background:rgba(148,163,184,0.15); }}
    html:not(.light) .bd-done     {{ color:#34d399; background:rgba(52,211,153,0.15); }}
    html:not(.light) .bd-closed   {{ color:#9ca3af; background:rgba(156,163,175,0.15); }}
    html:not(.light) .bd-open     {{ color:#60a5fa; background:rgba(96,165,250,0.18); }}
    html:not(.light) .bd-neutral  {{ color:#94a3b8; background:rgba(148,163,184,0.15); }}
    html:not(.light) .bd-high     {{ color:#f87171; background:rgba(248,113,113,0.15); }}
    html:not(.light) .bd-medium   {{ color:#60a5fa; background:rgba(96,165,250,0.12); }}
    html:not(.light) .bd-low      {{ color:#94a3b8; background:rgba(148,163,184,0.12); }}
    /* Sticky action column */
    .act-col {{ position:sticky; right:0; z-index:2; background:var(--bg-card); box-shadow:-3px 0 8px rgba(0,0,0,0.08); }}
    tr:hover .act-col {{ background:var(--bg-card); }}
    .empty-state {{ padding: 40px; text-align: center; color: var(--text-muted); font-size: 0.9rem; }}
    .no-results-row td {{
      text-align: center; color: var(--text-muted); font-size: 0.88rem; padding: 32px !important;
    }}

    /* ── Export button (per-table) ── */
    .export-btn {{
      background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 7px; color: var(--text-muted); font-size: 0.75rem; font-weight: 600;
      font-family: inherit; padding: 5px 12px; cursor: pointer; transition: all 0.15s;
      margin-left: auto;
    }}
    .export-btn:hover {{ color: var(--blue); border-color: var(--sb-active-bd); }}

    /* ── Action menu (flagged table) ── */
    .menu-btn {{
      background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 6px; color: var(--text-muted); font-size: 1.1rem;
      padding: 2px 8px; cursor: pointer; font-family: inherit; transition: all 0.15s;
      line-height: 1;
    }}
    .menu-btn:hover {{ color: var(--text-primary); border-color: var(--border); }}
    .action-menu {{
      display: none; position: fixed; z-index: 9999;
      background: var(--menu-bg); border: 1px solid var(--border);
      border-radius: 10px; padding: 6px; min-width: 200px;
      box-shadow: 0 8px 28px rgba(0,0,0,0.28); white-space: nowrap;
    }}
    .action-menu.open {{ display: block; }}
    .menu-item {{
      display: block; width: 100%; padding: 8px 12px; font-size: 0.82rem;
      color: var(--text-primary); background: none; border: none; text-align: left;
      border-radius: 6px; cursor: pointer; font-family: inherit; text-decoration: none;
      transition: background 0.12s;
    }}
    .menu-item:hover {{ background: var(--hover-row); }}
    .menu-item.success {{ color: var(--teal); }}
    tr.reviewed {{ opacity: 0.45; }}
    tr.reviewed td {{ text-decoration: line-through; text-decoration-color: var(--text-muted); }}

    /* ── Top-10 section ── */
    #top10-label {{ font-size: 0.78rem; color: var(--text-muted); margin: -4px 0 12px; }}

    @media (max-width: 1100px) {{
      .layout {{ flex-direction: column; }}
      .sidebar {{ width: 100%; position: static; max-height: 280px; }}
    }}
    @media (max-width: 900px) {{
      .cards {{ grid-template-columns: 1fr 1fr; }}
      .chart-row, .chart-row-2col {{ grid-template-columns: 1fr; }}
    }}

    /* ── Number text outline — both modes ── */
    .card .num {{
      -webkit-text-stroke: 2.5px rgba(0,0,0,0.85);
      paint-order: stroke fill;
    }}
    .banner-colored-num {{
      -webkit-text-stroke: 1.5px rgba(0,0,0,0.85);
      paint-order: stroke fill;
    }}

    /* ── Light mode border enhancements ── */
    html.light .card {{ border-color: rgba(0,0,0,0.16); }}
    html.light .card .num {{
      display: inline-block;
      border-radius: 10px;
      padding: 2px 14px 4px;
    }}
    html.light .chart-box  {{ border-color: rgba(0,0,0,0.16); }}
    html.light .total-banner {{ border-color: rgba(0,0,0,0.16); }}
    html.light .banner-colored-num {{
      display: inline-block;
      border-radius: 8px;
      padding: 1px 10px 3px;
    }}

    /* ── Status filter items ── */
    .status-filter-item {{ cursor: pointer; border-radius: 8px; padding: 4px 6px; transition: background 0.12s; }}
    .status-filter-item:hover {{ background: var(--hover-row); }}
    .status-active {{ background: rgba(96,165,250,0.12) !important; }}
    html.light .status-active {{ background: rgba(37,99,235,0.09) !important; }}

    /* ── Comment panel ── */
    .comment-panel {{
      background: var(--bg-card); border-top: 2px solid var(--blue);
      padding: 18px 22px 16px; border-radius: 0 0 10px 10px;
    }}
    .cp-header {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 14px;
    }}
    .cp-title {{ font-size: 0.88rem; font-weight: 700; color: var(--blue); }}
    .cp-close {{
      background: none; border: none; color: var(--text-muted);
      font-size: 1rem; cursor: pointer; padding: 2px 6px; border-radius: 4px;
    }}
    .cp-close:hover {{ color: var(--text-primary); background: var(--hover-row); }}
    .cp-comments {{
      max-height: 220px; overflow-y: auto; margin-bottom: 14px;
      border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px;
      background: var(--bg); scrollbar-width: thin;
    }}
    .cp-comment {{ margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid var(--border-soft); display: flex; gap: 8px; align-items: flex-start; }}
    .cp-comment:last-child {{ margin-bottom: 0; padding-bottom: 0; border-bottom: none; }}
    .cp-comment-new {{ animation: cpFadeIn 0.3s ease; }}
    @keyframes cpFadeIn {{ from {{ opacity:0; transform:translateY(6px); }} to {{ opacity:1; transform:translateY(0); }} }}
    .cp-comment-body {{ flex: 1; min-width: 0; }}
    .cp-comment-actions {{ display: flex; flex-direction: column; gap: 3px; flex-shrink: 0; opacity: 0; transition: opacity 0.15s; padding-top: 2px; }}
    .cp-comment:hover .cp-comment-actions {{ opacity: 1; }}
    .cp-act-btn {{ background: none; border: 1px solid transparent; border-radius: 4px; padding: 2px 8px; font-size: 0.68rem; cursor: pointer; color: var(--text-muted); font-family: inherit; transition: all 0.12s; white-space: nowrap; line-height: 1.6; }}
    .cp-act-btn:hover {{ border-color: var(--border); color: var(--text-primary); background: var(--hover-row); }}
    .cp-act-btn.del:hover {{ border-color: #ef4444; color: #ef4444; background: rgba(239,68,68,0.06); }}
    .cp-meta {{ display: flex; gap: 10px; align-items: baseline; margin-bottom: 4px; }}
    .cp-author {{ font-size: 0.78rem; font-weight: 700; color: var(--blue); }}
    .cp-date {{ font-size: 0.73rem; color: var(--text-muted); }}
    .cp-text {{ font-size: 0.83rem; color: var(--text-primary); line-height: 1.5; white-space: pre-wrap; word-break: break-word; }}
    .cp-empty {{ font-size: 0.82rem; color: var(--text-muted); text-align: center; padding: 18px 0; }}
    .cp-offline {{
      font-size: 0.82rem; color: var(--amber); text-align: center; padding: 14px 0;
      border: 1px dashed rgba(251,191,36,0.4); border-radius: 6px;
    }}
    .cp-compose {{ border-top: 1px solid var(--border); padding-top: 12px; }}
    .cp-who {{ font-size: 0.76rem; color: var(--text-muted); margin-bottom: 8px; }}
    .cp-who strong {{ color: var(--blue); }}
    .cp-change-name {{
      background: none; border: none; color: var(--blue); font-size: 0.73rem;
      cursor: pointer; text-decoration: underline; padding: 0; font-family: inherit;
    }}
    .cp-textarea {{
      width: 100%; background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 8px; padding: 9px 12px; color: var(--text-primary);
      font-size: 0.84rem; font-family: inherit; resize: vertical; outline: none;
      min-height: 72px;
    }}
    .cp-textarea:focus {{ border-color: rgba(96,165,250,0.5); }}
    .cp-actions {{ display: flex; gap: 8px; margin-top: 8px; }}
    .cp-submit {{
      background: var(--blue); border: none; border-radius: 7px;
      color: #0f1117; font-size: 0.8rem; font-weight: 700; padding: 7px 18px;
      cursor: pointer; font-family: inherit; transition: opacity 0.15s;
    }}
    .cp-submit:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    html.light .cp-submit {{ color: #fff; }}
    .cp-cancel-btn {{
      background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 7px; color: var(--text-muted); font-size: 0.8rem;
      padding: 7px 14px; cursor: pointer; font-family: inherit; transition: all 0.15s;
    }}
    .cp-cancel-btn:hover {{ color: var(--text-primary); border-color: var(--border); }}
    /* ── Name prompt modal ── */
    #name-prompt-overlay {{
      position: fixed; inset: 0; z-index: 99999;
      background: rgba(0,0,0,0.55); display: flex;
      align-items: center; justify-content: center;
    }}
    .name-prompt {{
      background: var(--bg-card); border: 1px solid var(--border);
      border-radius: 14px; padding: 28px 32px; width: 360px; max-width: 90vw;
      box-shadow: 0 16px 48px rgba(0,0,0,0.4);
    }}
    .name-prompt h3 {{ margin: 0 0 6px; font-size: 1rem; font-weight: 700; }}
    .name-prompt p {{ margin: 0 0 16px; font-size: 0.82rem; color: var(--text-muted); }}
    .name-prompt-input {{
      width: 100%; background: var(--input-bg); border: 1px solid var(--input-bd);
      border-radius: 8px; padding: 9px 12px; color: var(--text-primary);
      font-size: 0.9rem; font-family: inherit; outline: none; margin-bottom: 12px;
    }}
    .name-prompt-input:focus {{ border-color: rgba(96,165,250,0.5); }}
  </style>
</head>
<body>
<noscript>
<div style="position:fixed;top:0;left:0;right:0;z-index:99999;background:#1e40af;color:#fff;
  padding:18px 24px;font-family:system-ui,sans-serif;font-size:0.95rem;text-align:center;
  box-shadow:0 4px 12px rgba(0,0,0,0.4);">
  <strong>JavaScript is disabled</strong> &mdash; This dashboard requires JavaScript to display charts and interactive features.
  You are likely viewing this in <strong>SharePoint or OneDrive preview mode</strong>, which blocks scripts by design.
  <br><br>
  <span style="font-size:0.9rem;">To view the full dashboard: click the
    <strong>&nbsp;&#8942;&nbsp;</strong> (three-dot menu) at the top of this page
    and select <strong>Download</strong>, then open the downloaded file in your browser.
  </span>
</div>
</noscript>
<div class="page">

  <!-- Header -->
  <div class="header">
    <div>
      <h1>IT Open Ticket Dashboard</h1>
      <div class="sub" id="headerSub">Active unresolved tickets &mdash; created more than {MIN_DAYS_OPEN} days ago</div>
    </div>
    <div class="right">
      <span class="gen-time">Generated: {gen_date}</span>
      <span class="pill">Scope: {MIN_DAYS_OPEN}+ days &bull; {pages} page(s) fetched</span>
      {'<div class="view-toggle"><button class="vt-btn active" id="vt45" onclick="setView(\'45\')">45+ Days</button><button class="vt-btn" id="vtAll" onclick="setView(\'all\')">All Open</button></div>' if has_all else ''}
      <button class="theme-toggle" id="themeBtn" onclick="toggleTheme()">&#9788; Light Mode</button>
    </div>
  </div>

  {total_all_html}

  <div class="fetch-banner">
    Fetched <strong>{raw_total}</strong> raw tickets &rarr; <strong>{total}</strong> active after filtering
    resolved statuses &bull; cutoff date: <strong>{cutoff}</strong>
  </div>

  <div class="layout">

    <!-- Sidebar -->
    <div class="sidebar">
      <div class="sb-title">Filter by Assignee</div>
      <input class="sb-search" id="sbSearch" type="text" placeholder="Search name..." oninput="searchAssignees(this.value)">
      <button class="sb-all active" id="btnAll" onclick="clearFilter()">All Assignees</button>
      <div class="sb-divider"></div>
      <div id="sbList"></div>
      <div class="sb-divider"></div>
      <div class="sb-title" style="margin-top:4px;">Export</div>
      <button class="export-all-btn" onclick="exportAllTables()">&#8659; Download CSV</button>
    </div>

    <!-- Main content -->
    <div class="main-content" style="flex:1;min-width:0;">

      <div class="filter-indicator" id="filterIndicator">
        <span id="filterLabel">Showing all tickets</span>
        <button class="fi-clear" onclick="clearFilter()">Clear filter</button>
      </div>

      <!-- Stat cards -->
      <div class="cards">
        <div class="card blue"><div class="num" id="kpi-total">{total}</div><div class="lbl">Active tickets in scope</div></div>
        <div class="card teal"><div class="num" id="kpi-avg">{avg_days}</div><div class="lbl">Avg days open</div></div>
        <div class="card amber"><div class="num" id="kpi-stale">{len(stale_tickets)}</div><div class="lbl">No response {MIN_DAYS_OPEN}+ days</div></div>
        <div class="card red"><div class="num" id="kpi-unassigned">{unassigned}</div><div class="lbl">Unassigned tickets</div></div>
      </div>

      <!-- Analytics row: Age distribution + Status breakdown -->
      <div class="chart-row-2col">
        <div class="chart-box" id="box-ageChart">
          <div class="chart-label">Age Distribution (45d+ tickets)</div>
          <canvas id="ageChart" height="140"></canvas>
        </div>
        <div class="chart-box">
          <div class="chart-label">Status Breakdown</div>
          <div id="status-breakdown" style="overflow-y:auto;max-height:220px;"></div>
        </div>
      </div>

      <!-- Existing charts -->
      <div class="chart-row">
        <div class="chart-box" id="box-assigneeChart">
          <div class="chart-label">Tickets by Assignee (45d+ scope)</div>
          <canvas id="assigneeChart" height="110"></canvas>
        </div>
        <div class="chart-box" id="box-statusChart">
          <div class="chart-label">Tickets by Status</div>
          <canvas id="statusChart"></canvas>
        </div>
      </div>

      <div id="scope-45-sections">

      <!-- Table 1: Top 10 dynamic -->
      <div class="section-hd">
        <h2 id="top10-heading">Top 10 Longest Open Tickets</h2>
        <span class="count" id="top10-count">sorted by days open</span>
        <button class="export-btn" onclick="exportTable('tbl-oldest','oldest-tickets')">&#8659; Export</button>
      </div>
      <div id="top10-label">Showing global top 10. Select an assignee to see their longest tickets.</div>
      <div class="table-wrap"><div class="table-scroll">
        <table id="tbl-oldest" style="width:100%;border-collapse:collapse;table-layout:fixed;min-width:900px;">
          <colgroup>
            <col style="width:85px"><col style="width:210px"><col style="width:130px">
            <col style="width:115px"><col style="width:90px"><col style="width:130px">
            <col style="width:90px"><col style="width:75px"><col style="width:70px">
            <col style="width:80px">
          </colgroup>
          <thead><tr>
            <th {TH}>Ticket</th><th {TH}>Summary</th><th {TH}>Assignee</th>
            <th {TH}>Reporter</th><th {TH}>Created</th><th {TH}>Status</th>
            <th {TH_C}>Days Open</th><th {TH_C}>No Reply</th><th {TH_C}>Reports</th>
            <th {ACT_TH}>Actions</th>
          </tr></thead>
          <tbody id="top10-body"></tbody>
        </table>
      </div></div>

      <!-- Table 2: Flagged -->
      <div class="section-hd">
        <h2>Flagged Tickets &mdash; No Action Taken</h2>
        <span class="count" id="count-flagged">{len(flagged)} ticket(s)</span>
        <div class="sort-btns" id="flagged-sort-btns">
          <button class="sort-btn active" id="sort-desc" onclick="sortFlaggedTable('desc')" title="Oldest first (most days open)">&#8595; Oldest</button>
          <button class="sort-btn" id="sort-asc" onclick="sortFlaggedTable('asc')" title="Newest first (just crossed threshold)">&#8593; Newest</button>
        </div>
        <button class="export-btn" onclick="exportTable('tbl-flagged','flagged-tickets')">&#8659; Export</button>
      </div>
      <div class="section-sub">
        Tickets still unresolved across multiple report runs &mdash;
        <strong style="color:var(--red);">Times on Report</strong> increments each run.
        Use the <strong>&#8943;</strong> menu to take action.
      </div>
      <div class="table-wrap"><div class="table-scroll">{flagged_body}</div></div>

      </div><!-- /scope-45-sections -->

      <!-- All Open Tickets (shown in All Open mode only) -->
      <div id="all-open-section" style="display:none">
        <div class="section-hd">
          <h2>All Open Tickets</h2>
          <span class="count" id="all-open-count">0 ticket(s)</span>
          <button class="export-btn" onclick="exportTable('tbl-all-open','all-open-tickets')">&#8659; Export</button>
        </div>
        <div class="section-sub">All unresolved tickets regardless of age &mdash; 45d+ tickets include full enrichment data.</div>
        <div class="table-wrap"><div class="table-scroll">
          <table id="tbl-all-open" style="width:100%;border-collapse:collapse;table-layout:fixed;min-width:900px;">
            <colgroup>
              <col style="width:85px"><col style="width:210px"><col style="width:130px">
              <col style="width:115px"><col style="width:90px"><col style="width:130px">
              <col style="width:90px"><col style="width:75px"><col style="width:70px">
              <col style="width:80px">
            </colgroup>
            <thead><tr>
              <th {TH}>Ticket</th><th {TH}>Summary</th><th {TH}>Assignee</th>
              <th {TH}>Reporter</th><th {TH}>Created</th><th {TH}>Status</th>
              <th {TH_C}>Days Open</th><th {TH_C}>No Reply</th><th {TH_C}>Reports</th>
              <th {ACT_TH}>Actions</th>
            </tr></thead>
            <tbody id="all-open-body"></tbody>
          </table>
        </div></div>
      </div><!-- /all-open-section -->

      <!-- Table 3: Approaching -->
      <div id="approaching-section">
      <div class="section-hd">
        <h2>Approaching {MIN_DAYS_OPEN}-Day Threshold</h2>
        <span class="count">{len(approaching)} ticket(s)</span>
        <button class="export-btn" onclick="exportTable('tbl-approaching','approaching-tickets')">&#8659; Export</button>
      </div>
      <div class="section-sub">
        Unresolved tickets within {approaching_window} days of the threshold &mdash;
        <strong style="color:var(--amber);">resolve or assign now</strong>.
        <span style="color:var(--red);font-weight:600;">Red</span> = 2 days or fewer.
      </div>
      <div class="table-wrap"><div class="table-scroll">{approaching_body}</div></div>
      </div><!-- /approaching-section -->

    </div><!-- /main-content -->
  </div><!-- /layout -->
</div><!-- /page -->

<script>
/* ── Inline Chart.js ── */
{chartjs_inline}
</script>
<script>
/* ── Ticket data ── */
const ALL_TICKETS_45  = {tickets_json};
const ALL_TICKETS_ALL = {all_tickets_json};
const JIRA_MIN        = {MIN_DAYS_OPEN};

/* ── Global state ── */
let ALL_TICKETS    = ALL_TICKETS_45;
let currentView    = '45';
let activeAssignee = null;
let activeStatus   = null;

/* ── Color palette (hoisted for chart updates) ── */
var _palette = ['#60a5fa','#2dd4bf','#fbbf24','#f87171','#a78bfa','#fb7185','#34d399','#f97316','#38bdf8','#94a3b8'];
function _mkColors(n) {{ return Array.from({{length:n}}, (_,i) => _palette[i % _palette.length]); }}

/* ── Theme toggle ── */
function updateChartColors(isLight) {{
  var gridClr = isLight ? 'rgba(0,0,0,0.07)' : 'rgba(255,255,255,0.05)';
  var textClr = isLight ? '#475569' : '#64748b';
  if (typeof Chart === 'undefined') return;
  Chart.defaults.color = textClr;
  Chart.defaults.borderColor = gridClr;
  [ageChartObj, assigneeChartObj].forEach(function(c) {{
    if (!c) return;
    c.options.scales.y.grid.color = gridClr;
    c.options.scales.x.ticks.color = textClr;
    c.options.scales.y.ticks.color = textClr;
    c.update();
  }});
  if (statusChartObj) {{
    statusChartObj.options.plugins.legend.labels.color = textClr;
    statusChartObj.update();
  }}
}}
function toggleTheme() {{
  const isLight = document.documentElement.classList.toggle('light');
  document.getElementById('themeBtn').textContent = isLight ? '☀ Dark Mode' : '⚈ Light Mode';
  localStorage.setItem('theme', isLight ? 'light' : 'dark');
  if (typeof Chart !== 'undefined') updateChartColors(isLight);
}}
(function() {{
  try {{
    if (localStorage.getItem('theme') === 'light') {{
      document.documentElement.classList.add('light');
      const btn = document.getElementById('themeBtn');
      if (btn) btn.textContent = '☀ Dark Mode';
    }}
  }} catch(e) {{}}
}})();

/* ── Badge helpers ── */
function statusClass(k) {{
  if (k.includes('waiting'))     return 'bd-waiting';
  if (k.includes('in progress')) return 'bd-progress';
  if (k.includes('develop'))     return 'bd-develop';
  if (k.includes('valid'))       return 'bd-valid';
  if (k.includes('discover'))    return 'bd-discovery';
  if (k.includes('hold'))        return 'bd-hold';
  if (k.includes('pending'))     return 'bd-hold';
  if (['completed','done','fulfilled'].includes(k)) return 'bd-done';
  if (['canceled','cancelled','closed','resolved',"won't do",'duplicate','approved'].includes(k)) return 'bd-closed';
  if (k === 'open') return 'bd-open';
  return 'bd-neutral';
}}
function statusBadge(s) {{ return `<span class="badge ${{statusClass(s.toLowerCase())}}">${{esc(s)}}</span>`; }}
function esc(s) {{ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

/* ── Mailto builder (for dynamic rows) ── */
function _buildMailto(t) {{
  const first   = t.assignee.split(' ')[0];
  const subject = encodeURIComponent(`Follow-up Required: [${{t.key}}] ${{t.summary.substring(0,60)}}`);
  const body    = encodeURIComponent(
    `Hi ${{first}},\r\n\r\nThis is a follow-up regarding ticket ${{t.key}}: "${{t.summary}}".\r\n\r\n` +
    `This ticket has been open for ${{t.days}} days without resolution. Could you please provide a status update?\r\n\r\n` +
    `Ticket link: ${{t.url}}\r\n\r\nThank you,\r\nIT Management`
  );
  return `mailto:?subject=${{subject}}&body=${{body}}`;
}}

/* ── Flagged table sort ── */
let _flaggedSortDir = 'desc';
function sortFlaggedTable(dir) {{
  _flaggedSortDir = dir;
  const tbl = document.getElementById('tbl-flagged');
  if (!tbl) return;
  const tbody = tbl.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr[data-created]'));
  rows.sort((a, b) => {{
    const da = a.dataset.created || '';
    const db = b.dataset.created || '';
    return dir === 'asc' ? db.localeCompare(da) : da.localeCompare(db);
  }});
  rows.forEach(r => tbody.appendChild(r));
  document.getElementById('sort-asc').classList.toggle('active', dir === 'asc');
  document.getElementById('sort-desc').classList.toggle('active', dir === 'desc');
}}

/* ── Filter helpers ── */
function getFilteredPool() {{
  return ALL_TICKETS.filter(t =>
    (!activeAssignee || t.assignee === activeAssignee) &&
    (!activeStatus   || t.status   === activeStatus)
  );
}}

/* ── Sidebar rebuild (called when view switches or on init) ── */
function renderAssigneeButtons() {{
  const counts = {{}};
  ALL_TICKETS.forEach(t => {{ counts[t.assignee] = (counts[t.assignee] || 0) + 1; }});
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const maxCnt = sorted.length ? sorted[0][1] : 1;
  document.getElementById('sbList').innerHTML = sorted.map(([name, count]) => {{
    const pct    = Math.round(count / maxCnt * 100);
    const en     = esc(name);
    const active = activeAssignee === name ? ' active' : '';
    return `<div class="sb-item">
      <button class="assignee-btn${{active}}" data-name="${{en}}" onclick="filterByAssignee(this)">
        <span class="sb-name">${{en}}</span>
        <span class="sb-count">${{count}}</span>
      </button>
      <div class="sb-bar"><div class="sb-bar-fill" style="width:${{pct}}%"></div></div>
    </div>`;
  }}).join('');
  const q = document.getElementById('sbSearch');
  if (q && q.value) searchAssignees(q.value);
}}

/* ── View toggle ── */
function setView(mode) {{
  currentView    = mode;
  ALL_TICKETS    = (mode === '45') ? ALL_TICKETS_45 : ALL_TICKETS_ALL;
  activeAssignee = null;
  activeStatus   = null;
  const btn45 = document.getElementById('vt45');
  const btnAll = document.getElementById('vtAll');
  if (btn45) btn45.classList.toggle('active', mode === '45');
  if (btnAll) btnAll.classList.toggle('active', mode === 'all');
  const sub = document.getElementById('headerSub');
  if (sub) sub.textContent = mode === '45'
    ? 'Active unresolved tickets — created more than {MIN_DAYS_OPEN} days ago'
    : 'All active unresolved tickets — regardless of age';
  const ageLabel = document.querySelector('#box-ageChart .chart-label');
  if (ageLabel) ageLabel.textContent = mode === '45'
    ? 'Age Distribution (45d+ tickets)'
    : 'Age Distribution (all open tickets)';
  const approachSec  = document.getElementById('approaching-section');
  const scope45      = document.getElementById('scope-45-sections');
  const allOpenSec   = document.getElementById('all-open-section');
  if (approachSec) approachSec.style.display  = (mode === '45') ? '' : 'none';
  if (scope45)     scope45.style.display      = (mode === '45') ? '' : 'none';
  if (allOpenSec)  allOpenSec.style.display   = (mode === 'all') ? '' : 'none';
  renderAssigneeButtons();
  applyFilter();
}}

/* ── KPI card update ── */
function updateKPICards(pool) {{
  const total = pool.length;
  const avg   = total ? (pool.reduce((s,t) => s + t.days, 0) / total).toFixed(1) : 0;
  const stale = pool.filter(t => t.response >= JIRA_MIN).length;
  const unasn = pool.filter(t => t.assignee === 'Unassigned').length;
  document.getElementById('kpi-total').textContent      = total;
  document.getElementById('kpi-avg').textContent        = avg;
  document.getElementById('kpi-stale').textContent      = stale;
  document.getElementById('kpi-unassigned').textContent = unasn;
}}

/* ── Status breakdown widget (dynamic) ── */
function updateStatusBreakdown(pool) {{
  const el = document.getElementById('status-breakdown');
  if (!el) return;
  const counts = {{}};
  pool.forEach(t => {{ counts[t.status] = (counts[t.status] || 0) + 1; }});
  const sorted = Object.entries(counts).sort((a,b) => b[1] - a[1]);
  const total  = pool.length;
  const maxCnt = sorted.length ? sorted[0][1] : 1;
  el.innerHTML = sorted.map(([status, count]) => {{
    const pct  = Math.round(count / maxCnt * 100);
    const pctL = total ? Math.round(count / total * 100) : 0;
    const act  = status === activeStatus;
    return `<div class="status-filter-item${{act?' status-active':''}}" data-status="${{esc(status)}}" onclick="filterByStatus(this)">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
        ${{statusBadge(status)}}
        <span style="font-size:0.82rem;font-weight:600;color:var(--text-primary);">${{count}}<span style="color:var(--text-muted);font-weight:400;"> (${{pctL}}%)</span></span>
      </div>
      <div style="height:4px;background:var(--border);border-radius:2px;">
        <div style="height:4px;background:var(--blue);border-radius:2px;width:${{pct}}%;opacity:${{act?1:0.5}};"></div>
      </div>
    </div>`;
  }}).join('');
}}

/* ── Section counts ── */
function updateSectionCounts(pool) {{
  const el = document.getElementById('count-flagged');
  if (el) el.textContent = pool.filter(t => t.flagged >= 2).length + ' ticket(s)';
}}

/* ── All Open Tickets table (rendered in All Open mode) ── */
function renderAllOpenTable() {{
  const pool    = getFilteredPool();
  const sorted  = [...pool].sort((a, b) => b.days - a.days);
  const body    = document.getElementById('all-open-body');
  const countEl = document.getElementById('all-open-count');
  if (!body) return;
  if (countEl) countEl.textContent = sorted.length + ' ticket(s)';

  if (sorted.length === 0) {{
    body.innerHTML = '<tr class="no-results-row"><td colspan="10">No tickets match the current filter.</td></tr>';
    return;
  }}

  const TD     = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);"';
  const TD_C   = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;"';
  const TD_SUM = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"';
  const ACT_TD = 'class="act-col" style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;position:relative;"';
  body.innerHTML = sorted.map(t => {{
    const dc     = t.days >= 45 ? 'var(--red)' : (t.days >= 30 ? 'var(--amber)' : 'var(--text-muted)');
    const rc     = t.response >= JIRA_MIN ? 'var(--red)' : 'var(--text-muted)';
    const ek     = esc(t.key); const eu = esc(t.url); const es = esc(t.summary);
    const mailto = _buildMailto(t);
    return `<tr data-assignee="${{esc(t.assignee)}}" data-status="${{esc(t.status)}}" data-key="${{ek}}" data-url="${{eu}}" data-summary="${{es}}">
      <td ${{TD}}><a href="${{eu}}" target="_blank" class="ticket-link">${{ek}}</a></td>
      <td ${{TD_SUM}}>${{es}}</td>
      <td ${{TD}}>${{esc(t.assignee)}}</td>
      <td ${{TD}}>${{esc(t.reporter)}}</td>
      <td ${{TD}}>${{t.created || '—'}}</td>
      <td ${{TD}}>${{statusBadge(t.status)}}</td>
      <td ${{TD_C}}><span style="color:${{dc}};font-weight:600;">${{t.days}}</span></td>
      <td ${{TD_C}}><span style="color:${{rc}};font-weight:600;">${{t.response}}</span></td>
      <td ${{TD_C}}>${{t.flagged}}</td>
      <td ${{ACT_TD}}>
        <button class="menu-btn" onclick="toggleMenu(this)" title="More actions">&#8943;</button>
        <div class="action-menu">
          <a class="menu-item" href="${{eu}}" target="_blank">&#x1F517; View in Jira</a>
          <button class="menu-item" onclick="copyLink(this)">&#x1F4CB; Copy Link</button>
          <a class="menu-item" href="${{mailto}}">&#x2709; Send Follow-up Draft</a>
          <button class="menu-item" onclick="openCommentPanel(this,'${{ek}}')">&#x1F4AC; Add Comment</button>
          <button class="menu-item" onclick="toggleReviewed(this)">&#x2713; Mark as Reviewed</button>
          <button class="menu-item" onclick="copyTicketSummary(this)">&#x1F4DD; Copy Summary</button>
        </div>
      </td>
    </tr>`;
  }}).join('');
  body.querySelectorAll('tr[data-key]').forEach(function(row) {{
    if (localStorage.getItem('reviewed-' + row.dataset.key)) {{
      row.classList.add('reviewed');
      var btn = row.querySelector('[onclick*="toggleReviewed"]');
      if (btn) btn.textContent = '↺ Undo Reviewed';
    }}
  }});
}}

/* ── Top-10 dynamic table ── */
function renderTop10() {{
  const pool    = getFilteredPool();
  const sorted  = [...pool].sort((a,b) => b.days - a.days).slice(0, 10);
  const body    = document.getElementById('top10-body');
  const heading = document.getElementById('top10-heading');
  const label   = document.getElementById('top10-label');
  const countEl = document.getElementById('top10-count');

  const parts = [];
  if (activeAssignee) parts.push(activeAssignee);
  if (activeStatus)   parts.push(activeStatus);

  if (sorted.length === 0) {{
    body.innerHTML = '<tr class="no-results-row"><td colspan="10">No tickets match the current filter.</td></tr>';
    heading.textContent = parts.length ? `Top Tickets — ${{parts.join(' / ')}}` : 'Top 10 Longest Open Tickets';
    countEl.textContent = '0 tickets';
    label.textContent   = 'No tickets match the current filter.';
    return;
  }}

  heading.textContent = parts.length ? `Longest Open — ${{parts.join(' / ')}}` : 'Top 10 Longest Open Tickets';
  label.textContent   = parts.length
    ? `Showing ${{sorted.length}} longest open ticket${{sorted.length !== 1 ? 's' : ''}} for ${{parts.join(' / ')}}.`
    : 'Showing global top 10. Select an assignee or click a chart segment to filter.';
  countEl.textContent = `${{sorted.length}} ticket${{sorted.length !== 1 ? 's' : ''}}`;

  const TD     = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);"';
  const TD_C   = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;"';
  const TD_SUM = 'style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"';
  const ACT_TD = 'class="act-col" style="padding:11px 14px;font-size:0.84rem;border-bottom:1px solid var(--border-soft);text-align:center;position:relative;"';
  body.innerHTML = sorted.map(t => {{
    const dc  = t.days     >= 60       ? 'var(--red)' : 'var(--text-muted)';
    const rc  = t.response >= JIRA_MIN ? 'var(--red)' : 'var(--text-muted)';
    const ek  = esc(t.key); const eu = esc(t.url); const es = esc(t.summary);
    const mailto = _buildMailto(t);
    return `<tr data-assignee="${{esc(t.assignee)}}" data-status="${{esc(t.status)}}" data-key="${{ek}}" data-url="${{eu}}" data-summary="${{es}}">
      <td ${{TD}}><a href="${{eu}}" target="_blank" class="ticket-link">${{ek}}</a></td>
      <td ${{TD_SUM}}>${{es}}</td>
      <td ${{TD}}>${{esc(t.assignee)}}</td>
      <td ${{TD}}>${{esc(t.reporter)}}</td>
      <td ${{TD}}>${{t.created || '—'}}</td>
      <td ${{TD}}>${{statusBadge(t.status)}}</td>
      <td ${{TD_C}}><span style="color:${{dc}};font-weight:600;">${{t.days}}</span></td>
      <td ${{TD_C}}><span style="color:${{rc}};font-weight:600;">${{t.response}}</span></td>
      <td ${{TD_C}}>${{t.flagged}}</td>
      <td ${{ACT_TD}}>
        <button class="menu-btn" onclick="toggleMenu(this)" title="More actions">&#8943;</button>
        <div class="action-menu">
          <a class="menu-item" href="${{eu}}" target="_blank">&#x1F517; View in Jira</a>
          <button class="menu-item" onclick="copyLink(this)">&#x1F4CB; Copy Link</button>
          <a class="menu-item" href="${{mailto}}">&#x2709; Send Follow-up Draft</a>
          <button class="menu-item" onclick="openCommentPanel(this,'${{ek}}')">&#x1F4AC; Add Comment</button>
          <button class="menu-item" onclick="toggleReviewed(this)">&#x2713; Mark as Reviewed</button>
          <button class="menu-item" onclick="copyTicketSummary(this)">&#x1F4DD; Copy Summary</button>
        </div>
      </td>
    </tr>`;
  }}).join('');
  /* restore reviewed state for newly rendered rows */
  body.querySelectorAll('tr[data-key]').forEach(function(row) {{
    if (localStorage.getItem('reviewed-' + row.dataset.key)) {{
      row.classList.add('reviewed');
      var btn = row.querySelector('[onclick*="toggleReviewed"]');
      if (btn) btn.textContent = '↺ Undo Reviewed';
    }}
  }});
}}

/* ── Table row filter ── */
function filterTableRows() {{
  ['tbl-flagged','tbl-approaching'].forEach(function(id) {{
    const tbl = document.getElementById(id);
    if (!tbl) return;
    tbl.querySelectorAll('tbody tr[data-assignee]').forEach(function(row) {{
      const ma = !activeAssignee || row.dataset.assignee === activeAssignee;
      const ms = !activeStatus   || row.dataset.status   === activeStatus;
      row.style.display = (ma && ms) ? '' : 'none';
    }});
    const vis = tbl.querySelectorAll('tbody tr[data-assignee]:not([style*="display: none"])');
    let ph = tbl.querySelector('.no-results-row');
    if (vis.length === 0) {{
      if (!ph) {{
        ph = tbl.querySelector('tbody').insertRow();
        ph.className = 'no-results-row';
        const td = ph.insertCell(); td.colSpan = 20;
        td.textContent = 'No tickets match the current filter.';
      }}
      ph.style.display = '';
    }} else if (ph) {{
      ph.style.display = 'none';
    }}
  }});
}}

/* ── Master apply filter ── */
function applyFilter() {{
  const pool = getFilteredPool();
  if (currentView === '45') {{
    renderTop10();
    filterTableRows();
  }} else {{
    renderAllOpenTable();
  }}
  updateKPICards(pool);
  updateCharts(pool);
  updateStatusBreakdown(pool);
  updateSectionCounts(pool);
  updateFilterIndicator();
}}

function updateFilterIndicator() {{
  const ind   = document.getElementById('filterIndicator');
  const label = document.getElementById('filterLabel');
  const parts = [];
  if (activeAssignee) parts.push(`Assignee: ${{activeAssignee}}`);
  if (activeStatus)   parts.push(`Status: ${{activeStatus}}`);
  if (parts.length) {{
    label.textContent = parts.join(' · ') + ` — ${{getFilteredPool().length}} ticket(s)`;
    ind.classList.add('visible');
  }} else {{
    ind.classList.remove('visible');
  }}
}}

/* ── Assignee filter ── */
function filterByAssignee(btn) {{
  activeAssignee = btn.dataset.name;
  document.querySelectorAll('.assignee-btn').forEach(b => b.classList.toggle('active', b === btn));
  document.getElementById('btnAll').classList.remove('active');
  applyFilter();
}}

function clearFilter() {{
  activeAssignee = null;
  activeStatus   = null;
  document.querySelectorAll('.assignee-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('btnAll').classList.add('active');
  applyFilter();
}}

/* ── Status filter ── */
function filterByStatus(el) {{
  const s = (typeof el === 'string') ? el : el.dataset.status;
  activeStatus = (activeStatus === s) ? null : s;
  applyFilter();
}}

function searchAssignees(q) {{
  const lower = q.toLowerCase();
  document.querySelectorAll('#sbList .sb-item').forEach(item => {{
    item.style.display = item.querySelector('.assignee-btn').dataset.name.toLowerCase().includes(lower) ? '' : 'none';
  }});
}}

/* ── Action menu ── */
function _getMenuRow(el) {{
  const m = el.closest('.action-menu');
  return (m && m._sourceRow) || el.closest('tr');
}}
function _closeAllMenus() {{
  document.querySelectorAll('.action-menu.open').forEach(function(m) {{
    m.classList.remove('open');
    m.style.top = ''; m.style.right = ''; m.style.left = '';
    if (m._returnTo) {{
      m._returnTo.insertAdjacentElement('afterend', m);
      m._returnTo  = null;
      m._sourceRow = null;
    }}
  }});
}}
function toggleMenu(btn) {{
  const menu = btn.nextElementSibling;
  const isOpen = menu.classList.contains('open');
  _closeAllMenus();
  if (!isOpen) {{
    const r = btn.getBoundingClientRect();
    menu._sourceRow = btn.closest('tr');
    menu._returnTo  = btn;
    document.body.appendChild(menu);
    menu.style.top   = (r.bottom + 8) + 'px';
    menu.style.right = (window.innerWidth - r.right) + 'px';
    menu.style.left  = 'auto';
    menu.classList.add('open');
  }}
}}
document.addEventListener('click', function(e) {{
  if (!e.target.closest('.menu-btn') && !e.target.closest('.action-menu')) _closeAllMenus();
}});
window.addEventListener('scroll', _closeAllMenus, true);

function _copyText(text, btn) {{
  const orig = btn.textContent;
  function onSuccess() {{
    btn.textContent = '✓ Copied!'; btn.classList.add('success');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('success'); }}, 1800);
  }}
  function onFail() {{
    btn.textContent = '✗ Failed'; btn.classList.add('error');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('error'); }}, 1800);
  }}
  if (navigator.clipboard && window.isSecureContext) {{
    navigator.clipboard.writeText(text).then(onSuccess).catch(function() {{
      _copyFallback(text) ? onSuccess() : onFail();
    }});
  }} else {{
    _copyFallback(text) ? onSuccess() : onFail();
  }}
}}
function _copyFallback(text) {{
  try {{
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.focus(); ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  }} catch(e) {{ return false; }}
}}
function copyLink(btn) {{
  _copyText(_getMenuRow(btn).dataset.url, btn);
  _closeAllMenus();
}}
function copyTicketSummary(btn) {{
  const row  = _getMenuRow(btn);
  const text = '[' + row.dataset.key + '] ' + row.dataset.summary + '\\n' + row.dataset.url;
  _copyText(text, btn);
  _closeAllMenus();
}}

function toggleReviewed(btn) {{
  const row   = _getMenuRow(btn);
  const key   = row.dataset.key;
  const lsKey = 'reviewed-' + key;
  const isRev = row.classList.toggle('reviewed');
  localStorage.setItem(lsKey, isRev ? '1' : '');
  btn.textContent = isRev ? '↺ Undo Reviewed' : '✓ Mark as Reviewed';
  _closeAllMenus();
}}


/* ── CSV Export ── */
function exportTable(tableId, filename) {{
  const tbl = document.getElementById(tableId);
  if (!tbl) {{ exportAllTables(); return; }}
  const rows = [];
  rows.push(Array.from(tbl.querySelectorAll('thead th'))
    .map(th => '"' + th.textContent.trim().replace(/"/g,'""') + '"').join(','));
  tbl.querySelectorAll('tbody tr').forEach(row => {{
    if (row.style.display === 'none' || row.classList.contains('no-results-row')) return;
    const cells = Array.from(row.querySelectorAll('td')).map(td =>
      '"' + td.innerText.trim().replace(/"/g,'""') + '"');
    rows.push(cells.join(','));
  }});
  downloadCSV(rows.join('\\n'), filename + '.csv');
}}

function exportAllTables() {{
  const sections = currentView === '45'
    ? [
        {{id:'tbl-oldest',     label:'Longest Open'}},
        {{id:'tbl-flagged',    label:'Flagged'}},
        {{id:'tbl-approaching',label:'Approaching 45d'}},
      ]
    : [
        {{id:'tbl-all-open',   label:'All Open Tickets'}},
      ];
  const rows = [];
  sections.forEach(sec => {{
    const tbl = document.getElementById(sec.id);
    if (!tbl) return;
    rows.push('"--- ' + sec.label + ' ---"');
    rows.push(Array.from(tbl.querySelectorAll('thead th'))
      .map(th => '"' + th.textContent.trim().replace(/"/g,'""') + '"').join(','));
    tbl.querySelectorAll('tbody tr').forEach(row => {{
      if (row.style.display === 'none' || row.classList.contains('no-results-row')) return;
      rows.push(Array.from(row.querySelectorAll('td'))
        .map(td => '"' + td.innerText.trim().replace(/"/g,'""') + '"').join(','));
    }});
    rows.push('');
  }});
  const suffix = activeAssignee ? '-' + activeAssignee.replace(/[\\s]+/g,'-') : '-all';
  downloadCSV(rows.join('\\n'), 'jira-tickets' + suffix + '.csv');
}}

function downloadCSV(content, filename) {{
  const encoded = 'data:text/csv;charset=utf-8,' + encodeURIComponent(content);
  const a = document.createElement('a');
  a.setAttribute('href', encoded);
  a.setAttribute('download', filename);
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}}

/* ── Comment panel ── */
let _activePanelKey = null;
let _pendingKey     = null;
let _pendingBtn     = null;

function openCommentPanel(btn, key) {{
  _closeAllMenus();
  if (_activePanelKey === key) {{ closeCommentPanel(); return; }}
  closeCommentPanel();
  if (!localStorage.getItem('display-name')) {{
    _pendingKey = key; _pendingBtn = btn;
    _showNamePrompt(); return;
  }}
  _activePanelKey = key;
  const row = _getMenuRow(btn) || btn.closest('tr');
  if (!row) return;
  const panelRow = document.createElement('tr');
  panelRow.id = 'cp-panel-row';
  const name = esc(localStorage.getItem('display-name') || 'You');
  panelRow.innerHTML = `<td colspan="20" style="padding:0;">
    <div class="comment-panel">
      <div class="cp-header">
        <span class="cp-title">&#x1F4AC; Comments &mdash; ${{esc(key)}}</span>
        <button class="cp-close" onclick="closeCommentPanel()">&#x2715;</button>
      </div>
      <div class="cp-comments" id="cp-list">
        <div class="cp-empty">Loading&hellip;</div>
      </div>
      <div class="cp-compose">
        <div class="cp-who">Commenting as <strong>${{name}}</strong>
          <button class="cp-change-name" onclick="_showNamePrompt()">change</button>
        </div>
        <textarea class="cp-textarea" id="cp-input" placeholder="Write a comment&hellip;" rows="3"></textarea>
        <div class="cp-actions">
          <button class="cp-submit" id="cp-submit-btn" onclick="submitComment('${{key}}')">Submit Comment</button>
          <button class="cp-cancel-btn" onclick="closeCommentPanel()">Cancel</button>
        </div>
      </div>
    </div>
  </td>`;
  row.insertAdjacentElement('afterend', panelRow);
  _loadComments(key);
  setTimeout(() => document.getElementById('cp-input')?.focus(), 80);
}}

function closeCommentPanel() {{
  document.getElementById('cp-panel-row')?.remove();
  _activePanelKey = null;
}}

function _loadComments(key) {{
  const list = document.getElementById('cp-list');
  if (!list) return;
  fetch('/api/comments/' + key)
    .then(r => r.json())
    .then(d => _renderComments(d.comments || []))
    .catch(() => {{
      if (list) list.innerHTML =
        '<div class="cp-offline">&#9888; Comment posting requires the live network server URL &mdash; not available from this file or SharePoint.</div>';
    }});
}}

function _renderComments(comments) {{
  const list = document.getElementById('cp-list');
  if (!list) return;
  if (!comments.length) {{
    list.innerHTML = '<div class="cp-empty">No comments yet &mdash; be the first.</div>';
    return;
  }}
  const key = _activePanelKey;
  list.innerHTML = comments.map(c =>
    `<div class="cp-comment" data-id="${{esc(c.id)}}">
      <div class="cp-comment-body">
        <div class="cp-meta"><span class="cp-author">${{esc(c.author)}}</span><span class="cp-date">${{esc(c.created)}}</span></div>
        <div class="cp-text">${{esc(c.text)}}</div>
      </div>
      <div class="cp-comment-actions">
        <button class="cp-act-btn" onclick="editComment('${{key}}','${{esc(c.id)}}',this)">Edit</button>
        <button class="cp-act-btn del" onclick="deleteComment('${{key}}','${{esc(c.id)}}',this)">Delete</button>
      </div>
    </div>`
  ).join('');
  list.scrollTop = list.scrollHeight;
}}

function submitComment(key) {{
  const input  = document.getElementById('cp-input');
  const submitBtn = document.getElementById('cp-submit-btn');
  const rawText = (input?.value || '').trim();
  if (!rawText) return;
  const name = localStorage.getItem('display-name') || 'IT Management';
  const text = '[From: ' + name + '] ' + rawText;
  if (submitBtn) {{ submitBtn.disabled = true; submitBtn.textContent = 'Submitting…'; }}
  fetch('/api/comments/' + key, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ text }})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.error) throw new Error(d.error);
    const list = document.getElementById('cp-list');
    const empty = list?.querySelector('.cp-empty');
    if (empty) empty.remove();
    const div = document.createElement('div');
    div.className = 'cp-comment cp-comment-new';
    div.dataset.id = d.id;
    div.innerHTML = `<div class="cp-comment-body">
        <div class="cp-meta"><span class="cp-author">${{esc(name)}}</span><span class="cp-date">just now</span></div>
        <div class="cp-text">${{esc(rawText)}}</div>
      </div>
      <div class="cp-comment-actions">
        <button class="cp-act-btn" onclick="editComment('${{key}}','${{d.id}}',this)">Edit</button>
        <button class="cp-act-btn del" onclick="deleteComment('${{key}}','${{d.id}}',this)">Delete</button>
      </div>`;
    list?.appendChild(div);
    list.scrollTop = list.scrollHeight;
    if (input) input.value = '';
  }})
  .catch(err => alert('Could not post comment: ' + err.message))
  .finally(() => {{
    if (submitBtn) {{ submitBtn.disabled = false; submitBtn.textContent = 'Submit Comment'; }}
  }});
}}

/* ── Comment edit / delete ── */
function deleteComment(key, commentId, btn) {{
  if (!confirm('Delete this comment from Jira? This cannot be undone.')) return;
  btn.textContent = '…'; btn.disabled = true;
  fetch('/api/comments/' + key + '/' + commentId, {{ method: 'DELETE' }})
    .then(r => r.json())
    .then(d => {{
      if (d.error) throw new Error(d.error);
      btn.closest('.cp-comment').remove();
      const list = document.getElementById('cp-list');
      if (list && !list.querySelector('.cp-comment'))
        list.innerHTML = '<div class="cp-empty">No comments yet &mdash; be the first.</div>';
    }})
    .catch(err => {{ alert('Could not delete: ' + err.message); btn.textContent = 'Delete'; btn.disabled = false; }});
}}

function editComment(key, commentId, btn) {{
  const commentEl = btn.closest('.cp-comment');
  const body      = commentEl.querySelector('.cp-comment-body');
  const textEl    = body.querySelector('.cp-text');
  const orig      = textEl.textContent;
  const ta        = document.createElement('textarea');
  ta.className    = 'cp-textarea'; ta.style.marginTop = '6px'; ta.value = orig;
  const editBtns  = document.createElement('div');
  editBtns.className = 'cp-actions'; editBtns.style.marginTop = '6px';
  editBtns.dataset.orig = orig; editBtns.dataset.key = key; editBtns.dataset.cid = commentId;
  editBtns.innerHTML = '<button class="cp-submit" onclick="saveEdit(this)">Save</button> ' +
    '<button class="cp-cancel-btn" onclick="cancelEdit(this)">Cancel</button>';
  textEl.replaceWith(ta);
  body.appendChild(editBtns);
  commentEl.querySelector('.cp-comment-actions').style.visibility = 'hidden';
  ta.focus();
}}

function saveEdit(btn) {{
  const eb   = btn.closest('.cp-actions');
  const body = eb.closest('.cp-comment-body');
  const cel  = eb.closest('.cp-comment');
  const ta   = body.querySelector('textarea');
  const text = (ta.value || '').trim();
  if (!text) return;
  btn.disabled = true; btn.textContent = 'Saving…';
  fetch('/api/comments/' + eb.dataset.key + '/' + eb.dataset.cid, {{
    method: 'PUT', headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify({{ text }})
  }})
  .then(r => r.json())
  .then(d => {{
    if (d.error) throw new Error(d.error);
    const td = document.createElement('div');
    td.className = 'cp-text'; td.textContent = text;
    ta.replaceWith(td); eb.remove();
    cel.querySelector('.cp-comment-actions').style.visibility = '';
  }})
  .catch(err => {{ alert('Could not save: ' + err.message); btn.disabled = false; btn.textContent = 'Save'; }});
}}

function cancelEdit(btn) {{
  const eb   = btn.closest('.cp-actions');
  const body = eb.closest('.cp-comment-body');
  const cel  = eb.closest('.cp-comment');
  const ta   = body.querySelector('textarea');
  const td   = document.createElement('div');
  td.className = 'cp-text'; td.textContent = eb.dataset.orig;
  ta.replaceWith(td); eb.remove();
  cel.querySelector('.cp-comment-actions').style.visibility = '';
}}

/* ── Name prompt ── */
function _showNamePrompt() {{
  document.getElementById('name-prompt-overlay')?.remove();
  const existing = esc(localStorage.getItem('display-name') || '');
  const overlay  = document.createElement('div');
  overlay.id = 'name-prompt-overlay';
  overlay.innerHTML = `<div class="name-prompt">
    <h3>What&rsquo;s your name?</h3>
    <p>Shows on comments so others know who left them.<br>Saved in your browser &mdash; only asked once.</p>
    <input class="name-prompt-input" id="np-input" type="text"
      placeholder="Full name" value="${{existing}}" maxlength="60" autocomplete="name">
    <button class="cp-submit" style="width:100%;" onclick="_saveDisplayName()">Continue</button>
  </div>`;
  document.body.appendChild(overlay);
  const inp = document.getElementById('np-input');
  inp?.focus(); inp?.select();
  overlay.addEventListener('keydown', e => {{
    if (e.key === 'Enter') _saveDisplayName();
    if (e.key === 'Escape') {{ overlay.remove(); _pendingKey = null; _pendingBtn = null; }}
  }});
}}

function _saveDisplayName() {{
  const name = (document.getElementById('np-input')?.value || '').trim();
  if (!name) return;
  localStorage.setItem('display-name', name);
  document.getElementById('name-prompt-overlay')?.remove();
  if (_pendingKey) {{
    const k = _pendingKey, b = _pendingBtn;
    _pendingKey = null; _pendingBtn = null;
    openCommentPanel(b, k);
  }}
}}

document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeCommentPanel();
}});

/* ── Init ── */
renderAssigneeButtons();
renderTop10();
updateStatusBreakdown(ALL_TICKETS);
updateKPICards(ALL_TICKETS);
updateSectionCounts(ALL_TICKETS);
document.querySelectorAll('tr[data-key]').forEach(function(row) {{
  var key = row.dataset.key;
  if (localStorage.getItem('reviewed-' + key)) {{
    row.classList.add('reviewed');
    var btn = row.querySelector('[onclick*="toggleReviewed"]');
    if (btn) btn.textContent = '↺ Undo Reviewed';
  }}
}});

/* ── Charts ── */
function _chartErr(boxId, msg) {{
  var box = document.getElementById(boxId);
  if (box) box.insertAdjacentHTML('beforeend',
    '<p style="color:#f87171;font-size:0.78rem;margin-top:8px;">&#9888; ' + msg + '</p>');
  console.error(boxId, msg);
}}

let ageChartObj = null, assigneeChartObj = null, statusChartObj = null;

/* ── Dynamic chart update (called by applyFilter) ── */
function updateCharts(pool) {{
  if (typeof Chart === 'undefined') return;

  if (ageChartObj) {{
    let b;
    if (currentView === '45') {{
      b = {{'45-60d':0,'60-90d':0,'90-180d':0,'180d+':0}};
      pool.forEach(t => {{
        if      (t.days < 60)  b['45-60d']++;
        else if (t.days < 90)  b['60-90d']++;
        else if (t.days < 180) b['90-180d']++;
        else                   b['180d+']++;
      }});
    }} else {{
      b = {{'<45d':0,'45-90d':0,'90-180d':0,'180d+':0}};
      pool.forEach(t => {{
        if      (t.days < 45)  b['<45d']++;
        else if (t.days < 90)  b['45-90d']++;
        else if (t.days < 180) b['90-180d']++;
        else                   b['180d+']++;
      }});
    }}
    ageChartObj.data.labels = Object.keys(b);
    ageChartObj.data.datasets[0].data = Object.values(b);
    ageChartObj.update();
  }}

  if (assigneeChartObj) {{
    const counts = {{}};
    pool.forEach(t => {{ counts[t.assignee] = (counts[t.assignee] || 0) + 1; }});
    const sorted = Object.entries(counts).sort((a,b) => b[1] - a[1]);
    const light  = document.documentElement.classList.contains('light');
    assigneeChartObj.data.labels = sorted.map(([k]) => k);
    assigneeChartObj.data.datasets[0].data = sorted.map(([,v]) => v);
    assigneeChartObj.data.datasets[0].backgroundColor = sorted.map(([k], i) =>
      (activeAssignee && k === activeAssignee) ? (light ? '#1d4ed8' : '#3b82f6') : _palette[i % _palette.length]
    );
    assigneeChartObj.update();
  }}

  if (statusChartObj) {{
    const counts = {{}};
    pool.forEach(t => {{ counts[t.status] = (counts[t.status] || 0) + 1; }});
    const sorted = Object.entries(counts).sort((a,b) => b[1] - a[1]);
    statusChartObj.data.labels = sorted.map(([k]) => k);
    statusChartObj.data.datasets[0].data = sorted.map(([,v]) => v);
    statusChartObj.data.datasets[0].backgroundColor = _mkColors(sorted.length);
    statusChartObj.update();
  }}
}}

(function() {{
  if (typeof Chart === 'undefined') {{
    ['box-ageChart','box-assigneeChart','box-statusChart'].forEach(function(id) {{
      _chartErr(id, 'Chart.js bundle failed to execute. Open DevTools (F12) &rarr; Console for details.');
    }});
    return;
  }}

  Chart.defaults.color       = '#64748b';
  Chart.defaults.borderColor = 'rgba(255,255,255,0.06)';

  var ttOpts = {{
    backgroundColor:'#1e2433', titleColor:'#94a3b8',
    bodyColor:'#f1f5f9', borderColor:'rgba(255,255,255,0.1)', borderWidth:1
  }};

  try {{
    ageChartObj = new Chart(document.getElementById('ageChart'), {{
      type: 'bar',
      data: {{
        labels: {json.dumps(list(age_buckets.keys()))},
        datasets: [{{ label:'Tickets', data:{json.dumps(list(age_buckets.values()))},
          backgroundColor:['#60a5fa','#fbbf24','#f97316','#f87171'],
          borderRadius:6, borderSkipped:false, borderColor:'rgba(0,0,0,0.8)', borderWidth:2 }}]
      }},
      options: {{
        responsive:true,
        plugins:{{ legend:{{display:false}}, tooltip:ttOpts }},
        scales:{{
          y:{{beginAtZero:true, grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#64748b',precision:0}}}},
          x:{{grid:{{display:false}}, ticks:{{color:'#64748b'}}}}
        }}
      }}
    }});
  }} catch(e) {{ _chartErr('box-ageChart', 'ageChart: ' + e.message); }}

  try {{
    assigneeChartObj = new Chart(document.getElementById('assigneeChart'), {{
      type: 'bar',
      data: {{
        labels: {json.dumps(list(assignee_counts.keys()))},
        datasets: [{{ label:'Tickets', data:{json.dumps(list(assignee_counts.values()))},
          backgroundColor:_mkColors({len(assignee_counts)}),
          borderRadius:6, borderSkipped:false, borderColor:'rgba(0,0,0,0.8)', borderWidth:2,
          maxBarThickness:72 }}]
      }},
      options: {{
        responsive:true,
        onClick: function(evt, elements) {{
          if (!elements.length) return;
          const name = this.data.labels[elements[0].index];
          const btn  = document.querySelector(`.assignee-btn[data-name="${{name}}"]`);
          if (btn) {{ activeAssignee === name ? clearFilter() : filterByAssignee(btn); }}
        }},
        plugins:{{ legend:{{display:false}}, tooltip:ttOpts }},
        scales:{{
          y:{{beginAtZero:true, grid:{{color:'rgba(255,255,255,0.05)'}}, ticks:{{color:'#64748b',precision:0}}}},
          x:{{grid:{{display:false}}, ticks:{{color:'#64748b',maxRotation:35,font:{{size:11}}}}}}
        }}
      }}
    }});
  }} catch(e) {{ _chartErr('box-assigneeChart', 'assigneeChart: ' + e.message); }}

  try {{
    Chart.register({{
      id:'centerText',
      beforeDraw: function(chart) {{
        if (chart.config.type !== 'doughnut') return;
        var ca = chart.chartArea;
        if (!ca) return;
        var ctx = chart.ctx;
        var cx  = (ca.left + ca.right)  / 2;
        var cy  = (ca.top  + ca.bottom) / 2;
        var tot = chart.data.datasets[0].data.reduce(function(a,b){{return a+b;}}, 0);
        var light = document.documentElement.classList.contains('light');
        ctx.save();
        ctx.font      = 'bold 28px system-ui,sans-serif';
        ctx.fillStyle = light ? '#0f172a' : '#f1f5f9';
        ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
        ctx.fillText(tot, cx, cy - 9);
        ctx.font      = '12px system-ui,sans-serif';
        ctx.fillStyle = '#64748b';
        ctx.fillText('Total', cx, cy + 14);
        ctx.restore();
      }}
    }});
    statusChartObj = new Chart(document.getElementById('statusChart'), {{
      type:'doughnut',
      data: {{
        labels: {json.dumps(list(status_counts.keys()))},
        datasets: [{{ data:{json.dumps(list(status_counts.values()))},
          backgroundColor:_mkColors({len(status_counts)}), borderWidth:2, borderColor:'#161b27', hoverOffset:10 }}]
      }},
      options: {{
        responsive:true, cutout:'62%',
        onClick: function(evt, elements) {{
          if (!elements.length) return;
          filterByStatus(this.data.labels[elements[0].index]);
        }},
        plugins:{{
          centerText:true,
          legend:{{position:'bottom', labels:{{padding:14,font:{{size:11}},color:'#64748b',boxWidth:12,borderRadius:3}}}},
          tooltip:ttOpts
        }}
      }}
    }});
  }} catch(e) {{ _chartErr('box-statusChart', 'statusChart: ' + e.message); }}

  if (document.documentElement.classList.contains('light')) updateChartColors(true);
}})();
</script>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Dashboard generated: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_csv",   nargs="?", default="jira_report.csv")
    parser.add_argument("output_html", nargs="?", default="jira_report.html")
    args = parser.parse_args()

    browser_base_url = normalize_jira_url(
        os.getenv("JIRA_BASE_URL", "https://yourcompany.atlassian.net/rest/api/3")  # placeholder default — set JIRA_BASE_URL in .env
    )
    tickets     = load_tickets(args.input_csv)
    metadata    = load_metadata()
    approaching = load_approaching()
    all_tickets = load_all_tickets(
        os.path.join(os.path.dirname(args.input_csv) or ".", "jira_report_all.csv"),
        tickets,
    )
    if not tickets:
        raise SystemExit("No tickets found in input CSV.")
    make_html_report(tickets, args.output_html, browser_base_url, metadata, approaching, all_tickets)
