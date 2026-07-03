# Jira Ticket Reporting System

This Python script connects to Jira Cloud and generates a CSV report of unresolved IT tickets that are over 45 days old, including performance metrics like days open, last response dates, and flagging counts.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure environment variables in `.env`:
   ```
   JIRA_EMAIL=your-email@domain.com
   JIRA_API_TOKEN=your-api-token
   JIRA_BASE_URL=https://your-domain.atlassian.net/rest/api/3
   JIRA_PROJECT_KEY=IT
   ```

3. Get your Jira API token from: https://id.atlassian.com/manage-profile/security/api-tokens

## Usage

Run the fetch script:
```bash
python jira_fetcher.py
```

This will generate `jira_report.csv` with the following columns:
- ticket_key
- summary
- assignee
- status
- priority
- created_date
- days_open
- last_response_date
- days_since_last_response
- times_flagged

The fetcher paginates through every matching issue, not just the first 100 results.
Only tickets older than 45 days are included, and unresolved issues are filtered by `status != Done`.

Then generate a visual dashboard from the CSV:
```bash
python jira_report_visualizer.py
```

This will produce `jira_report.html`, a clean browser dashboard with charts and a top-ticket table.

## Requirements

- Python 3.8+
- Valid Jira API token with appropriate permissions
- Access to the specified Jira project

## Troubleshooting

- **410 Gone error**: Check that your API token is valid and not expired
- **403 Forbidden**: Ensure your account has permission to access the Jira project
- **Rate limiting**: The script includes automatic retry with exponential backoff

## Notes

- Only fetches unresolved tickets (status != Done) that are over 45 days old
- Handles pagination automatically
- Includes rate limiting protection
- Times are in UTC
