# Jira IT Ticket Reporting System — Developer Documentation

> **Purpose:** Automatically pull all active, unresolved IT tickets older than 45 days from Jira,
> generate a dark-themed HTML dashboard, and email a digest to the IT team each morning.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Project Structure](#2-project-structure)
3. [Prerequisites](#3-prerequisites)
4. [Initial Setup](#4-initial-setup)
5. [Running the Pipeline](#5-running-the-pipeline)
6. [Understanding the Dashboard](#6-understanding-the-dashboard)
7. [Understanding the Email Digest](#7-understanding-the-email-digest)
8. [Automated Scheduling](#8-automated-scheduling)
9. [Configuration Reference](#9-configuration-reference)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Project Overview

This system connects to your organization's Jira instance (e.g. `yourcompany.atlassian.net` —
set via `JIRA_BASE_URL` in `.env`) using the Jira REST API v3, fetches every open ticket in the
configured project (`JIRA_PROJECT_KEY`, defaults to the generic example `IT`) created more than
45 days ago, and produces:

- **`jira_report.csv`** — raw data file with one row per active ticket
- **`jira_report.html`** — interactive dark-themed dashboard with charts and tables
- **`jira_report_metadata.json`** — run statistics (pages fetched, totals, cutoff date)
- An **Outlook email digest** sent automatically each morning at 9:00 AM

The pipeline runs in three sequential steps, each as its own Python script, chained together
by `run_report.bat` which is triggered by Windows Task Scheduler.

> 📸 **[INSERT IMAGE HERE]**
> *Full screenshot of the dark-themed HTML dashboard open in a browser, showing the header,
> stat cards, charts, and the top of the ticket table.*

---

## 2. Project Structure

```
C:\JiraReporter\
│
├── jira_fetcher.py            # Step 1 — pulls data from Jira API → CSV
├── jira_report_visualizer.py  # Step 2 — reads CSV → HTML dashboard
├── jira_emailer.py            # Step 3 — reads CSV → sends Outlook email
├── run_report.bat             # Wrapper — chains all 3 steps with logging
│
├── .env                       # Credentials and config (never commit this)
├── .gitignore                 # Excludes .env, CSV, HTML, logs from git
├── requirements.txt           # Python package dependencies
├── DOCUMENTATION.md           # This file
│
├── jira_report.csv            # Output — regenerated on every run
├── jira_report.html           # Output — regenerated on every run
├── jira_report_metadata.json  # Output — regenerated on every run
│
└── logs\                      # One log file per run_report.bat execution
    └── run_YYYY-MM-DD_HHMMSS.log
```

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the `C:\JiraReporter` folder in Windows Explorer showing all files above.*

---

## 3. Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.8+ | Tested on 3.14. Install from python.org. |
| pip packages | see below | Install via `python -m pip install -r requirements.txt` |
| Jira API token | — | Personal token — see Section 4.3 below |
| Microsoft Outlook | Any modern version | Must be installed and signed in for email sending |
| Windows OS | Windows 10/11 | Required for Outlook COM automation and Task Scheduler |

**Python packages** (`requirements.txt`):
```
requests==2.31.0       # HTTP calls to Jira REST API
python-dotenv==1.0.0   # Loads .env file into environment variables
pywin32==306           # Windows COM automation for Outlook email sending
```

---

## 4. Initial Setup

### 4.1 Download the project

Place all files into `C:\JiraReporter\`. The scripts use relative file paths so the working
directory must be `C:\JiraReporter\` when running them.

### 4.2 Install Python dependencies

Open PowerShell and run:

```powershell
cd C:\JiraReporter
python -m pip install -r requirements.txt
```

### 4.3 Get a Jira API token

1. Go to: https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a name (e.g. "JiraReporter") and click **Create**
4. Copy the token — you will only see it once

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the Atlassian API token creation page at id.atlassian.com, showing the
> "Create API token" button and a newly created token ready to copy.*

### 4.4 Configure the `.env` file

Open `C:\JiraReporter\.env` and fill in your values:

```env
# Jira credentials
JIRA_EMAIL=your-email@yourcompany.com
JIRA_API_TOKEN=your-api-token-here
JIRA_BASE_URL=https://yourcompany.atlassian.net/rest/api/3
JIRA_PROJECT_KEY=IT

# Email settings
EMAIL_TO=it-team@yourcompany.com
# EMAIL_CC=manager@yourcompany.com   ← uncomment to add CC recipient
```

> All values above are placeholders — replace them with your own Jira domain, credentials,
> project key, and recipient addresses.

> **Important:** The `.env` file contains credentials. It is listed in `.gitignore` and must
> never be committed to source control or shared.

---

## 5. Running the Pipeline

The pipeline has three steps. Run them in order from `C:\JiraReporter\`:

### Step 1 — Fetch data from Jira

```powershell
python jira_fetcher.py
```

**What it does:**
- Queries Jira using JQL: all IT tickets older than 45 days, excluding resolved statuses
- Paginates through all results using `nextPageToken` (Jira Cloud pagination)
- For each ticket, fetches the most recent comment and counts Impediment flag events
- Writes `jira_report.csv` and `jira_report_metadata.json`

**Expected runtime:** 20–40 minutes for 1,000+ tickets (API rate limiting and per-ticket enrichment calls)

**Expected output:**
```
2026-05-07 11:29:04 [INFO] JQL: project = IT AND status NOT IN (...) AND created < -45d ...
                                              ^ "IT" here is the example JIRA_PROJECT_KEY value — yours will show whatever project key you configured
2026-05-07 11:29:05 [INFO] Fetching page 1 (startAt=0, token=no)...
2026-05-07 11:29:05 [INFO]   -> Page 1: 100 issues (running total: 100)
2026-05-07 11:29:05 [INFO]   (using nextPageToken for next page)
...
2026-05-07 11:51:16 [INFO] Done! 1065 active tickets saved to jira_report.csv
```

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the PowerShell terminal showing the fetcher running — visible pagination log
> lines ("Fetching page X", "-> Page X: 100 issues") and the final "Done!" summary line.*

### Step 2 — Generate the HTML dashboard

```powershell
python jira_report_visualizer.py
```

**What it does:**
- Reads `jira_report.csv` and `jira_report_metadata.json`
- Applies a safety filter to exclude any resolved-status tickets still in the CSV
- Writes `jira_report.html` — a self-contained dark-themed dashboard

**Expected runtime:** Under 5 seconds

**Open the dashboard:**
```powershell
Start-Process jira_report.html
```

### Step 3 — Send the email digest

```powershell
python jira_emailer.py
```

**What it does:**
- Reads `jira_report.csv` and `jira_report_metadata.json`
- Builds an HTML email with stat cards, top assignees, and the 15 oldest tickets
- Sends it via Outlook COM automation (Outlook must be open and signed in)

**Expected output:**
```
Email sent to: it-team@yourcompany.com
```

### Running everything at once

The batch file chains all three steps and logs output automatically:

```powershell
.\run_report.bat
```

If any step fails, the batch file stops immediately and logs the error. Subsequent steps will
not run until the issue is resolved.

**Log files** are written to `C:\JiraReporter\logs\` with a timestamp in the filename:
```
logs\run_2026-05-07_090001.log
```

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the `C:\JiraReporter\logs\` folder in Windows Explorer showing several
> timestamped log files from past runs.*

---

## 6. Understanding the Dashboard

Open `jira_report.html` in any modern browser after running Step 2.

### Header and confirmation banner

Shows the report date, scope (tickets older than 45 days), and a green banner confirming
how many raw tickets were fetched vs. how many active tickets remain after filtering.

### Stat cards

| Card | Colour | What it means |
|---|---|---|
| Active tickets in scope | Blue | Total unresolved tickets older than 45 days |
| Avg days open | Teal | Mean age of all active tickets |
| No response 45+ days | Amber | Tickets with zero comments or updates in 45+ days |
| Unassigned tickets | Red | Tickets with no assignee — highest priority to action |

> 📸 **[INSERT IMAGE HERE]**
> *Close-up screenshot of the four stat cards showing their coloured numbers and labels.*

### Charts

**Tickets by Assignee (bar chart):** Shows how many active tickets each person owns.
Useful for identifying agents with the heaviest unresolved backlog.

**Tickets by Status (donut chart):** Breakdown of active tickets by Jira status category.
The total count is shown in the centre of the donut. Hover over a segment to see details.

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the two charts side by side — the bar chart on the left and the donut chart
> on the right with the total displayed in the centre.*

### Top 20 Longest Open Tickets table

Sorted by days open (oldest first). Columns:

| Column | Description |
|---|---|
| Ticket | Clickable link to the Jira issue |
| Summary | Ticket title |
| Assignee | Person responsible |
| Status | Colour-coded pill (Open, In Progress, Waiting, etc.) |
| Priority | Colour-coded pill (High = red, Medium = blue, Low = grey) |
| Days Open | Days since ticket was created — red if 60+ |
| Days Since Response | Days since the last comment — red if 45+ |
| Flagged | Number of times the Impediment flag was set |

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the "Top 20 Longest Open Tickets" table showing several rows with coloured
> status and priority badges and red-highlighted days columns.*

### Flagged Tickets — No Action Taken table

Shows only tickets where `times_flagged > 0` — meaning the ticket was escalated at least once
via the Jira Impediment flag but still has no resolution.

| Column | Description |
|---|---|
| Times Flagged | How many times an agent was escalated/reached out to |
| Days Open | Total age of the ticket |
| Days Since Response | How long since anything happened on this ticket |

If no tickets have been flagged, a green "all clear" message is shown instead.

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the "Flagged Tickets — No Action Taken" section. If tickets exist, show the
> table with red Times Flagged numbers. If empty, show the "No flagged tickets found" message.*

---

## 7. Understanding the Email Digest

The email is sent automatically via Outlook each morning at 9:00 AM. It contains:

- **Blue header** — report title and generated date
- **Green confirmation banner** — raw fetched count vs. active tickets after filtering
- **Four stat cards** — same metrics as the dashboard
- **Top 5 assignees** — ranked by ticket count
- **Top 15 oldest tickets table** — with red highlighting for stale responses

The email uses table-based HTML layout (not CSS grid or flexbox) for maximum compatibility
with Outlook's rendering engine, which strips most modern CSS.

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the received email open in Outlook, showing the blue header, stat cards,
> assignee list, and the ticket table with red-highlighted response days.*

### Adding recipients

To add your manager or additional recipients, edit `C:\JiraReporter\.env`:

```env
EMAIL_TO=it-team@yourcompany.com
EMAIL_CC=manager@yourcompany.com
```

For multiple CC recipients, separate with semicolons:
```env
EMAIL_CC=manager@yourcompany.com;director@yourcompany.com
```

---

## 8. Automated Scheduling

The pipeline is registered as a Windows Scheduled Task named `JiraReporter\DailyReport`.
It runs `run_report.bat` every day at **9:00 AM**, but only when you are logged in
(required because Outlook COM automation needs an active Windows session).

### Viewing the scheduled task

```powershell
schtasks /query /tn "JiraReporter\DailyReport" /fo LIST
```

You can also view and edit it in the **Task Scheduler** GUI:
1. Press `Win + R`, type `taskschd.msc`, press Enter
2. Expand `Task Scheduler Library` → `JiraReporter`
3. Double-click `DailyReport` to view or edit

> 📸 **[INSERT IMAGE HERE]**
> *Screenshot of the Windows Task Scheduler GUI open to JiraReporter\DailyReport, showing
> the task details panel with Next Run Time, Status, and Triggers visible.*

### Changing the run time

```powershell
schtasks /change /tn "JiraReporter\DailyReport" /st 08:00
```

### Triggering a manual run

```powershell
schtasks /run /tn "JiraReporter\DailyReport"
```

### Disabling the task (e.g. during holidays)

```powershell
schtasks /change /tn "JiraReporter\DailyReport" /disable
# Re-enable:
schtasks /change /tn "JiraReporter\DailyReport" /enable
```

---

## 9. Configuration Reference

All configuration lives in `C:\JiraReporter\.env`. Restart any script after making changes.

| Variable | Required | Default | Description |
|---|---|---|---|
| `JIRA_EMAIL` | Yes | — | Your Atlassian account email address |
| `JIRA_API_TOKEN` | Yes | — | Personal Jira API token from id.atlassian.com |
| `JIRA_BASE_URL` | Yes | — | Full REST API base URL including `/rest/api/3` |
| `JIRA_PROJECT_KEY` | Yes | `IT` | Jira project key to query (e.g. `IT`) |
| `EMAIL_TO` | Yes | — | Primary recipient email address |
| `EMAIL_CC` | No | *(empty)* | CC recipients, semicolon-separated |

**Constants inside the scripts** (edit the `.py` files to change these):

| Constant | File | Default | Description |
|---|---|---|---|
| `MIN_DAYS_OPEN` | all three | `45` | Minimum ticket age in days to include in the report |
| `TOP_N` | `jira_emailer.py` | `15` | Number of tickets shown in the email table |

---

## 10. Troubleshooting

### `EnvironmentError: Missing JIRA_EMAIL or JIRA_API_TOKEN`
The `.env` file is missing or the variables are misspelled. Verify the file exists at
`C:\JiraReporter\.env` and that both variables are set.

### `401 Unauthorized` from Jira
Your API token has expired or is incorrect. Generate a new one at
https://id.atlassian.com/manage-profile/security/api-tokens and update `.env`.

### `403 Forbidden` from Jira
Your Atlassian account does not have permission to view the IT project.
Contact your Jira admin to verify project access.

### Rate limiting (many `Rate limited. Waiting Xs...` log lines)
Normal behaviour when fetching 1,000+ tickets. The script automatically waits and retries.
The full run may take up to 40 minutes — do not interrupt it.

### `ModuleNotFoundError: No module named 'win32com'`
pywin32 is not installed. Run:
```powershell
python -m pip install pywin32
```

### Email not sending / Outlook COM error
- Confirm Outlook is installed and you are logged in with a valid account
- Confirm the scheduled task is set to "Interactive only" (required for COM)
- Try running `python jira_emailer.py` manually while Outlook is open

### Dashboard shows resolved/completed tickets
The CSV was generated with older code. Re-run `python jira_report_visualizer.py` — it
filters resolved statuses from the CSV automatically. For fully clean data, re-run
`python jira_fetcher.py` to regenerate the CSV with the updated JQL.

### Scheduled task ran but nothing happened
Check the log file in `C:\JiraReporter\logs\` for the error. Common causes:
- You were not logged in when the task fired (task requires interactive session)
- A script failed mid-run and stopped the chain — the log shows which step and why
