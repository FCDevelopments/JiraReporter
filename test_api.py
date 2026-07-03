import os, base64, time, sys
import requests
from dotenv import load_dotenv
load_dotenv()
EMAIL     = os.getenv("JIRA_EMAIL")
TOKEN     = os.getenv("JIRA_API_TOKEN")
BASE_URL  = os.getenv("JIRA_BASE_URL", "https://yourcompany.atlassian.net/rest/api/3")  # placeholder default — set JIRA_BASE_URL in .env
PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "IT")  # generic example project key — change via JIRA_PROJECT_KEY in .env
creds     = base64.b64encode(f"{EMAIL}:{TOKEN}".encode()).decode()
session   = requests.Session()
session.headers.update({"Authorization": f"Basic {creds}", "Content-Type": "application/json", "Accept": "application/json"})
JQL       = f"project = {PROJECT_KEY} AND statusCategory != Done AND issuetype not in subTaskIssueTypes() AND created < -45d ORDER BY created DESC"
token = None
for page in range(1, 6):
    body = {"jql": JQL, "maxResults": 100, "fields": ["summary"]}
    if token:
        body["nextPageToken"] = token
    print(f"Sending page {page}...", flush=True)
    try:
        resp = session.post(f"{BASE_URL}/search/jql", json=body, timeout=30)
        print(f"Page {page}: HTTP {resp.status_code}", flush=True)
        if resp.status_code != 200:
            print(f"  Body: {resp.text[:300]}", flush=True)
            break
        data = resp.json()
        print(f"Page {page}: {len(data.get('issues',[]))} issues, isLast={data.get('isLast')}", flush=True)
        token = data.get("nextPageToken")
        if data.get("isLast") or not token:
            print("Done.", flush=True)
            break
    except Exception as e:
        print(f"Page {page} EXCEPTION: {type(e).__name__}: {e}", flush=True)
        break
    time.sleep(2)
print("Script finished.", flush=True)
