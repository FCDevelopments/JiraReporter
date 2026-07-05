# jira_fetcher.ps1 - Jira data fetcher using PowerShell Invoke-RestMethod
# A PowerShell-native alternative to jira_fetcher.py: use this variant when your
# environment's endpoint-protection policy interferes with the Python HTTP client.
# Same requests, just made through Invoke-RestMethod instead.
# Outputs: jira_report.csv, jira_approaching.csv, jira_report_metadata.json

[CmdletBinding()]
param()

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = $PSScriptRoot
if (-not $SCRIPT_DIR) { $SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path }

# Load .env file
$envFile = Join-Path $SCRIPT_DIR ".env"
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.+?)\s*$') {
        [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
    }
}

$EMAIL    = $env:JIRA_EMAIL
$TOKEN    = $env:JIRA_API_TOKEN
$BASE_URL = if ($env:JIRA_BASE_URL)     { $env:JIRA_BASE_URL }     else { "https://yourcompany.atlassian.net/rest/api/3" }  # placeholder default — set JIRA_BASE_URL in .env
$PROJECT  = if ($env:JIRA_PROJECT_KEY) { $env:JIRA_PROJECT_KEY } else { "IT" }
$MIN_DAYS = 45
$WINDOW   = 7

if (-not $EMAIL -or -not $TOKEN) {
    Write-Error "Missing JIRA_EMAIL or JIRA_API_TOKEN in .env"
    exit 1
}

$CREDS   = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${EMAIL}:${TOKEN}"))
$HEADERS = @{
    "Authorization" = "Basic $CREDS"
    "Content-Type"  = "application/json"
    "Accept"        = "application/json"
}

$RESOLVED = @("done","completed","fulfilled","canceled","cancelled","closed","resolved","won't do","duplicate","approved")

# POST helper with retries
function Invoke-JiraPost {
    param($Url, $Body)
    for ($a = 0; $a -lt 3; $a++) {
        try {
            $json = $Body | ConvertTo-Json -Compress -Depth 10
            return Invoke-RestMethod -Uri $Url -Method POST -Headers $HEADERS -Body $json -ContentType "application/json" -TimeoutSec 30
        } catch {
            Write-Host "  [WARN] POST attempt $($a+1): $($_.Exception.Message)"
            if ($a -eq 2) { return $null }
            Start-Sleep -Seconds ([Math]::Pow(2, $a))
        }
    }
    return $null
}

# GET helper with retries
function Invoke-JiraGet {
    param($Url, [hashtable]$Params = @{})
    if ($Params.Count -gt 0) {
        $qs = ($Params.GetEnumerator() | ForEach-Object { "$($_.Key)=$([Uri]::EscapeDataString($_.Value.ToString()))" }) -join "&"
        $Url = "${Url}?${qs}"
    }
    for ($a = 0; $a -lt 3; $a++) {
        try {
            return Invoke-RestMethod -Uri $Url -Method GET -Headers $HEADERS -TimeoutSec 15
        } catch {
            Write-Host "  [WARN] GET attempt $($a+1): $($_.Exception.Message)"
            if ($a -eq 2) { return $null }
            Start-Sleep -Seconds ([Math]::Pow(2, $a))
        }
    }
    return $null
}

# --- Fetch main issues (45+ days open) ---
$JQL = "project = $PROJECT AND statusCategory != Done AND issuetype not in subTaskIssueTypes() AND created < -${MIN_DAYS}d ORDER BY created DESC"
Write-Host "JQL: $JQL"

$FIELDS = @("summary","status","assignee","created","updated","priority","labels","resolutiondate","issuetype","reporter")
$allIssues = [System.Collections.Generic.List[object]]::new()
$pageNum   = 1
$nextToken = $null
$isLast    = $false

do {
    Write-Host "Fetching page $pageNum..."
    $body = @{ jql = $JQL; maxResults = 100; fields = $FIELDS }
    if ($nextToken) { $body["nextPageToken"] = $nextToken }
    $data = Invoke-JiraPost "$BASE_URL/search/jql" $body
    if (-not $data -or -not $data.issues) {
        Write-Host "  [ERROR] No data for page $pageNum - stopping."
        break
    }
    foreach ($iss in $data.issues) { $allIssues.Add($iss) }
    Write-Host "  -> Page ${pageNum}: $($data.issues.Count) issues (total: $($allIssues.Count))"
    $nextToken = $data.nextPageToken
    $isLast    = [bool]$data.isLast
    $pageNum++
    if (-not $isLast -and $nextToken) { Start-Sleep -Seconds 1 }
} while (-not $isLast -and $nextToken)

$pagesUsed = $pageNum - 1
$totalRaw  = $allIssues.Count
Write-Host "Last page reached. Total issues fetched: $totalRaw"

# --- Load tracker ---
$trackerPath = Join-Path $SCRIPT_DIR "ticket_tracker.json"
$trackerHash = [System.Collections.Generic.Dictionary[string,int]]::new()
if (Test-Path $trackerPath) {
    try {
        $raw = Get-Content $trackerPath -Raw | ConvertFrom-Json
        $raw.PSObject.Properties | ForEach-Object { $trackerHash[$_.Name] = [int]$_.Value }
    } catch {
        Write-Host "[WARN] ticket_tracker.json unreadable - starting fresh."
    }
}

# --- Enrich issues ---
$records         = [System.Collections.Generic.List[object]]::new()
$skippedResolved = 0
$skippedAge      = 0
$skippedError    = 0
$now             = [DateTime]::UtcNow

for ($i = 0; $i -lt $allIssues.Count; $i++) {
    $issue  = $allIssues[$i]
    $key    = $issue.key
    $fields = $issue.fields
    Write-Host "[$($i+1)/$totalRaw] Enriching $key..."
    try {
        $status = if ($fields.status -and $fields.status.name) { $fields.status.name } else { "Unknown" }
        if ($RESOLVED -contains $status.ToLower().Trim()) { $skippedResolved++; continue }
        if ($fields.issuetype -and $fields.issuetype.subtask) { continue }

        $createdStr = $fields.created
        $createdDt  = if ($createdStr) { [DateTime]::Parse($createdStr).ToUniversalTime() } else { $now }
        # Always use (now - created) for open tickets.
        # Some tickets have a stale resolutiondate from a prior resolve-then-reopen;
        # using it would produce an artificially low days_open and silently drop the ticket.
        $daysOpen   = [int]($now - $createdDt).TotalDays

        if ($daysOpen -lt $MIN_DAYS) { $skippedAge++; continue }

        $assignee = if ($fields.assignee -and $fields.assignee.displayName) { $fields.assignee.displayName } else { "Unassigned" }
        $reporter = if ($fields.reporter -and $fields.reporter.displayName) { $fields.reporter.displayName } else { "Unknown" }
        $priority = if ($fields.priority -and $fields.priority.name)        { $fields.priority.name }        else { "None" }
        $summary  = if ($fields.summary) { $fields.summary } else { "No Summary" }

        $lastResponseStr   = "No Response"
        $daysSinceResponse = $daysOpen
        $commentData = Invoke-JiraGet "$BASE_URL/issue/$key/comment" @{ orderBy = "-created"; maxResults = "1" }
        if ($commentData -and $commentData.comments -and $commentData.comments.Count -gt 0) {
            $lastResponseStr   = $commentData.comments[0].created
            $lastResponseDt    = [DateTime]::Parse($lastResponseStr).ToUniversalTime()
            $daysSinceResponse = [int]($now - $lastResponseDt).TotalDays
        }

        if ($trackerHash.ContainsKey($key)) { $trackerHash[$key]++ } else { $trackerHash[$key] = 1 }

        $records.Add([PSCustomObject]@{
            ticket_key          = $key
            summary             = $summary
            assignee            = $assignee
            reporter            = $reporter
            status              = $status
            priority            = $priority
            created_date        = $createdStr
            days_open           = $daysOpen
            last_response_date  = $lastResponseStr
            days_since_response = $daysSinceResponse
            times_flagged       = $trackerHash[$key]
        })
    } catch {
        Write-Host "  [ERROR] $key failed: $($_.Exception.Message) - skipping"
        $skippedError++
    }
    Start-Sleep -Milliseconds 200
}

Write-Host "Skipped: $skippedResolved resolved, $skippedAge under ${MIN_DAYS}d, $skippedError errors"

# --- Save tracker ---
$trackerObj = [PSCustomObject]@{}
foreach ($kv in $trackerHash.GetEnumerator()) {
    $trackerObj | Add-Member -MemberType NoteProperty -Name $kv.Key -Value $kv.Value
}
$trackerObj | ConvertTo-Json -Depth 5 | Out-File $trackerPath -Encoding utf8

# --- Save main CSV ---
$outputPath = Join-Path $SCRIPT_DIR "jira_report.csv"
$records | Export-Csv -Path $outputPath -NoTypeInformation -Encoding utf8
Write-Host "Saved $($records.Count) records to jira_report.csv"

# --- Fetch ALL open tickets (for dashboard toggle view + total count) ---
Write-Host "Fetching all open tickets..."
$totalAll       = 0
$allOpenRecords = [System.Collections.Generic.List[object]]::new()
$countToken     = $null
$countLast      = $false
do {
    $body = @{ jql = "project = $PROJECT AND statusCategory != Done AND issuetype not in subTaskIssueTypes()"; maxResults = 100; fields = @("summary","status","assignee","created","priority","issuetype","reporter") }
    if ($countToken) { $body["nextPageToken"] = $countToken }
    $data = Invoke-JiraPost "$BASE_URL/search/jql" $body
    if (-not $data -or -not $data.issues) { break }
    foreach ($issue in $data.issues) {
        $totalAll++
        $f = $issue.fields
        if ($f.issuetype -and $f.issuetype.subtask) { continue }
        $allOpenRecords.Add([PSCustomObject]@{
            ticket_key   = $issue.key
            summary      = if ($f.summary) { $f.summary } else { "No Summary" }
            assignee     = if ($f.assignee -and $f.assignee.displayName) { $f.assignee.displayName } else { "Unassigned" }
            reporter     = if ($f.reporter -and $f.reporter.displayName) { $f.reporter.displayName } else { "Unknown" }
            status       = if ($f.status -and $f.status.name) { $f.status.name } else { "Unknown" }
            priority     = if ($f.priority -and $f.priority.name) { $f.priority.name } else { "None" }
            created_date = if ($f.created) { $f.created } else { "" }
        })
    }
    $countToken = $data.nextPageToken
    $countLast  = [bool]$data.isLast
    Start-Sleep -Milliseconds 500
} while (-not $countLast -and $countToken)
Write-Host "Total unresolved IT tickets: $totalAll"
$allOpenRecords | Export-Csv (Join-Path $SCRIPT_DIR "jira_report_all.csv") -NoTypeInformation -Encoding utf8
Write-Host "Saved $($allOpenRecords.Count) all-open records to jira_report_all.csv"

# --- Fetch approaching tickets ---
Write-Host "Fetching approaching tickets..."
$approachJQL     = "project = $PROJECT AND statusCategory != Done AND issuetype not in subTaskIssueTypes() AND created <= -$($MIN_DAYS - $WINDOW)d AND created > -${MIN_DAYS}d ORDER BY created ASC"
$approachIssues  = [System.Collections.Generic.List[object]]::new()
$aToken          = $null
$aLast           = $false
do {
    $body = @{ jql = $approachJQL; maxResults = 100; fields = @("summary","status","assignee","created","priority","issuetype") }
    if ($aToken) { $body["nextPageToken"] = $aToken }
    $data = Invoke-JiraPost "$BASE_URL/search/jql" $body
    if (-not $data -or -not $data.issues) { break }
    foreach ($iss in $data.issues) { $approachIssues.Add($iss) }
    $aToken = $data.nextPageToken
    $aLast  = [bool]$data.isLast
    Start-Sleep -Milliseconds 500
} while (-not $aLast -and $aToken)

$approachRecords = [System.Collections.Generic.List[object]]::new()
foreach ($issue in $approachIssues) {
    $key    = $issue.key
    $fields = $issue.fields
    $status = if ($fields.status -and $fields.status.name) { $fields.status.name } else { "Unknown" }
    if ($RESOLVED -contains $status.ToLower().Trim()) { continue }
    if ($fields.issuetype -and $fields.issuetype.subtask) { continue }
    $createdStr  = $fields.created
    $createdDt   = if ($createdStr) { [DateTime]::Parse($createdStr).ToUniversalTime() } else { $now }
    $daysOpen    = [int]($now - $createdDt).TotalDays
    $daysUntil45 = [Math]::Max(0, $MIN_DAYS - $daysOpen)
    $assignee    = if ($fields.assignee -and $fields.assignee.displayName) { $fields.assignee.displayName } else { "Unassigned" }
    $priority    = if ($fields.priority -and $fields.priority.name)        { $fields.priority.name }        else { "None" }
    $summary     = if ($fields.summary) { $fields.summary } else { "No Summary" }
    $approachRecords.Add([PSCustomObject]@{
        ticket_key    = $key
        summary       = $summary
        assignee      = $assignee
        status        = $status
        priority      = $priority
        created_date  = $createdStr
        days_open     = $daysOpen
        days_until_45 = $daysUntil45
    })
}
$approachRecords = $approachRecords | Sort-Object days_until_45
Write-Host "Approaching tickets found: $($approachRecords.Count)"

$approachPath = Join-Path $SCRIPT_DIR "jira_approaching.csv"
if ($approachRecords.Count -gt 0) {
    $approachRecords | Export-Csv -Path $approachPath -NoTypeInformation -Encoding utf8
} elseif (Test-Path $approachPath) {
    Remove-Item $approachPath
}

# --- Save metadata ---
$meta = [ordered]@{
    generated_at       = $now.ToString("o")
    jql                = $JQL
    min_days_open      = $MIN_DAYS
    approaching_window = $WINDOW
    cutoff_date        = $now.AddDays(-$MIN_DAYS).ToString("o")
    pages_fetched      = $pagesUsed
    total_fetched      = $totalRaw
    records_saved      = $records.Count
    total_all_statuses = $totalAll
    approaching_count  = $approachRecords.Count
}
$meta | ConvertTo-Json | Out-File (Join-Path $SCRIPT_DIR "jira_report_metadata.json") -Encoding utf8

Write-Host "Done! $($records.Count) active tickets saved to jira_report.csv"
Write-Host "$($approachRecords.Count) approaching tickets saved to jira_approaching.csv"
Write-Host "Metadata saved to jira_report_metadata.json"
