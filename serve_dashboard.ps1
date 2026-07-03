# serve_dashboard.ps1 - Local network dashboard server (PowerShell + raw TCP)
#
# Uses System.Net.Sockets.TcpListener instead of HttpListener.
# TcpListener uses the OS socket API directly - no HTTP.sys, no URL ACL,
# no admin rights required. Works as a standard (non-admin) user.
#
# Routes:
#   GET  /                         -> dashboard HTML
#   GET  /api/comments/{issueKey}  -> fetch comments from Jira
#   POST /api/comments/{issueKey}  -> post a new comment to Jira
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File C:\JiraReporter\serve_dashboard.ps1

[CmdletBinding()]
param([int]$Port = 8080)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$SCRIPT_DIR = $PSScriptRoot
if (-not $SCRIPT_DIR) { $SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path }

$DASHBOARD = Join-Path $SCRIPT_DIR "jira_report.html"
$LOG_DIR   = Join-Path $SCRIPT_DIR "logs"
$LOG_FILE  = Join-Path $LOG_DIR "dashboard_server.log"

if (-not (Test-Path $LOG_DIR)) { New-Item -ItemType Directory -Path $LOG_DIR | Out-Null }

# --- Logging ---

function Write-Log {
    param([string]$Level = "INFO", [string]$Msg)
    $ts   = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "$ts [$Level] $Msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

# --- Load .env ---

$CFG = @{}
$envPath = Join-Path $SCRIPT_DIR ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*?)\s*=\s*(.+?)\s*$') {
            $CFG[$Matches[1].Trim()] = $Matches[2].Trim()
        }
    }
} else {
    Write-Log "WARN" ".env not found - comment proxy will not work."
}

$BASE_URL = if ($CFG["JIRA_BASE_URL"])     { $CFG["JIRA_BASE_URL"] }     else { "https://yourcompany.atlassian.net/rest/api/3" }  # placeholder default — set JIRA_BASE_URL in .env
$EMAIL    = if ($CFG["JIRA_EMAIL"])        { $CFG["JIRA_EMAIL"] }        else { "" }
$TOKEN    = if ($CFG["JIRA_API_TOKEN"])    { $CFG["JIRA_API_TOKEN"] }    else { "" }
$PROJECT  = if ($CFG["JIRA_PROJECT_KEY"]) { $CFG["JIRA_PROJECT_KEY"] }  else { "IT" }

$CREDS    = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("${EMAIL}:${TOKEN}"))
$JIRA_HDR = @{
    "Authorization" = "Basic $CREDS"
    "Content-Type"  = "application/json"
    "Accept"        = "application/json"
}
$KEY_RE = [regex]::new("^${PROJECT}-\d+$", [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)

# --- ADF extractor ---

function Get-AdfText {
    param($Node)
    if ($null -eq $Node) { return "" }
    if ($Node.type -eq "text") { return [string]$Node.text }
    $parts = [System.Collections.Generic.List[string]]::new()
    foreach ($child in $Node.content) {
        $p = Get-AdfText $child
        if ($p) { $parts.Add($p) }
    }
    $blocks = @("paragraph","listItem","heading","bulletList","orderedList")
    $sep = if ($blocks -contains $Node.type) { "`n" } else { " " }
    return ($parts -join $sep).Trim()
}

# --- Sanitize user input ---

function Invoke-Sanitize {
    param([string]$Text)
    $Text = [System.Net.WebUtility]::HtmlDecode($Text)
    $Text = [regex]::Replace($Text, '<[^>]+>', '')
    $Text = $Text.Trim()
    if ($Text.Length -gt 2000) { $Text = $Text.Substring(0, 2000) }
    return $Text
}

# --- Jira API ---

function Get-JiraComments {
    param([string]$Key)
    $url  = "$BASE_URL/issue/$Key/comment?maxResults=50&orderBy=created"
    $data = Invoke-RestMethod -Uri $url -Method GET -Headers $JIRA_HDR -TimeoutSec 15
    $out  = [System.Collections.Generic.List[hashtable]]::new()
    foreach ($c in $data.comments) {
        $out.Add(@{
            id      = [string]$c.id
            author  = if ($c.author -and $c.author.displayName) { [string]$c.author.displayName } else { "Unknown" }
            text    = Get-AdfText $c.body
            created = if ($c.created) { [string]$c.created.Substring(0,10) } else { "" }
        })
    }
    return @($out)
}

function Remove-JiraComment {
    param([string]$Key, [string]$CommentId)
    $url = "$BASE_URL/issue/$Key/comment/$CommentId"
    Invoke-RestMethod -Uri $url -Method DELETE -Headers $JIRA_HDR -TimeoutSec 15
}

function Update-JiraComment {
    param([string]$Key, [string]$CommentId, [string]$Text)
    $url  = "$BASE_URL/issue/$Key/comment/$CommentId"
    $body = @{
        body = @{
            version = 1
            type    = "doc"
            content = @(
                @{
                    type    = "paragraph"
                    content = @( @{ type = "text"; text = $Text } )
                }
            )
        }
    } | ConvertTo-Json -Depth 10 -Compress
    return Invoke-RestMethod -Uri $url -Method PUT -Headers $JIRA_HDR -Body $body -ContentType "application/json" -TimeoutSec 15
}

function Add-JiraComment {
    param([string]$Key, [string]$Text)
    $url  = "$BASE_URL/issue/$Key/comment"
    $body = @{
        body = @{
            version = 1
            type    = "doc"
            content = @(
                @{
                    type    = "paragraph"
                    content = @( @{ type = "text"; text = $Text } )
                }
            )
        }
    } | ConvertTo-Json -Depth 10 -Compress
    return Invoke-RestMethod -Uri $url -Method POST -Headers $JIRA_HDR -Body $body -ContentType "application/json" -TimeoutSec 15
}

# --- URL parts extraction ---

function Get-UrlParts {
    param([string]$RawUrl)
    $parts = $RawUrl.Split('?')[0].TrimStart('/').Split('/')
    $raw   = if ($parts.Count -ge 3) { $parts[2].ToUpper() } else { "" }
    $key   = if ($KEY_RE.IsMatch($raw)) { $raw } else { $null }
    $cid   = if ($parts.Count -ge 4 -and $parts[3]) { $parts[3] } else { "" }
    return @{ Key = $key; CommentId = $cid }
}

function Get-IssueKey {
    param([string]$RawUrl)
    return (Get-UrlParts $RawUrl).Key
}

function Get-CommentId {
    param([string]$RawUrl)
    return (Get-UrlParts $RawUrl).CommentId
}

# --- HTTP primitives ---

function Read-HttpRequest {
    param($Stream)

    # Read byte-by-byte until the \r\n\r\n header terminator
    $buf = [System.Collections.Generic.List[byte]]::new(4096)
    $n   = 0
    while ($true) {
        $b = $Stream.ReadByte()
        if ($b -lt 0) { return $null }
        $buf.Add([byte]$b)
        $n++
        if ($n -ge 4 -and
            $buf[$n-4] -eq 13 -and $buf[$n-3] -eq 10 -and
            $buf[$n-2] -eq 13 -and $buf[$n-1] -eq 10) { break }
        if ($n -gt 32768) { return $null }
    }

    $lines    = [Text.Encoding]::UTF8.GetString($buf.ToArray()).TrimEnd() -split "`r`n"
    $reqParts = $lines[0] -split ' '
    $method   = $reqParts[0]
    $rawUrl   = if ($reqParts.Count -ge 2) { $reqParts[1] } else { "/" }

    $hdrs = @{}
    for ($i = 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^([^:]+):\s*(.+)$') { $hdrs[$Matches[1]] = $Matches[2] }
    }

    $bodyBytes = [byte[]]@()
    $cl = $hdrs["Content-Length"]
    if ($cl -and ($len = [int]$cl) -gt 0 -and $len -le 1048576) {
        $bodyBytes = New-Object byte[] $len
        $off = 0
        while ($off -lt $len) {
            $r = $Stream.Read($bodyBytes, $off, $len - $off)
            if ($r -le 0) { break }
            $off += $r
        }
    }

    return @{ Method = $method; RawUrl = $rawUrl; Headers = $hdrs; BodyBytes = $bodyBytes }
}

$STATUS_TEXT = @{
    200 = "OK"
    204 = "No Content"
    400 = "Bad Request"
    404 = "Not Found"
    500 = "Internal Server Error"
    502 = "Bad Gateway"
    503 = "Service Unavailable"
}

function Write-RawResponse {
    param($Stream, [int]$Status, [string]$CT, [byte[]]$Body, [hashtable]$Extra = @{})
    $st  = if ($STATUS_TEXT[$Status]) { $STATUS_TEXT[$Status] } else { "Unknown" }
    $hdr = [System.Collections.Generic.List[string]]::new()
    $hdr.Add("HTTP/1.1 $Status $st")
    $hdr.Add("Content-Type: $CT")
    $hdr.Add("Content-Length: $($Body.Length)")
    $hdr.Add("Connection: close")
    foreach ($k in $Extra.Keys) { $hdr.Add("${k}: $($Extra[$k])") }
    $hdrBytes = [Text.Encoding]::UTF8.GetBytes(($hdr -join "`r`n") + "`r`n`r`n")
    $Stream.Write($hdrBytes, 0, $hdrBytes.Length)
    if ($Body.Length -gt 0) { $Stream.Write($Body, 0, $Body.Length) }
    $Stream.Flush()
}

function Write-JsonResp {
    param($Stream, $Data, [int]$Status = 200)
    $bytes = [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json $Data -Depth 10 -Compress))
    Write-RawResponse $Stream $Status "application/json; charset=utf-8" $bytes @{
        "Access-Control-Allow-Origin" = "*"
    }
}

function Write-ErrResp {
    param($Stream, [int]$Status, [string]$Msg)
    Write-RawResponse $Stream $Status "text/plain; charset=utf-8" ([Text.Encoding]::UTF8.GetBytes($Msg))
}

# --- Start TCP listener (no admin / URL ACL needed) ---

$tcp = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $Port)
$tcp.Start()

$localIPs = @()
try {
    [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
        Where-Object { $_.AddressFamily -eq "InterNetwork" -and $_.ToString() -ne "127.0.0.1" } |
        ForEach-Object { $localIPs += $_.ToString() }
} catch {}

Write-Log "INFO" "Dashboard server started on port $Port"
Write-Log "INFO" "Dashboard file: $DASHBOARD"
foreach ($ip in $localIPs) { Write-Log "INFO" "  -> http://${ip}:$Port" }
Write-Log "INFO" "Press Ctrl+C to stop."

# --- Request loop ---

try {
    while ($true) {
        $client = $tcp.AcceptTcpClient()
        $client.ReceiveTimeout = 5000
        $client.SendTimeout    = 10000

        try {
            $stream = $client.GetStream()
            $req    = Read-HttpRequest $stream
            if (-not $req) { $client.Close(); continue }

            $method = $req.Method
            $rawUrl = $req.RawUrl
            Write-Log "INFO" "$($client.Client.RemoteEndPoint) $method $rawUrl"

            # OPTIONS preflight
            if ($method -eq "OPTIONS") {
                Write-RawResponse $stream 204 "text/plain" ([byte[]]@()) @{
                    "Access-Control-Allow-Origin"  = "*"
                    "Access-Control-Allow-Methods" = "GET, POST, PUT, DELETE, OPTIONS"
                    "Access-Control-Allow-Headers" = "Content-Type"
                }
                $client.Close()
                continue
            }

            # GET / -> dashboard HTML
            if ($method -eq "GET" -and ($rawUrl -eq "/" -or $rawUrl -eq "/index.html" -or $rawUrl -eq "/jira_report.html")) {
                if (-not (Test-Path $DASHBOARD)) {
                    Write-ErrResp $stream 503 "Dashboard not yet generated - run jira_fetcher.ps1 first"
                } else {
                    $bytes    = [IO.File]::ReadAllBytes($DASHBOARD)
                    $modified = (Get-Item $DASHBOARD).LastWriteTime.ToString("yyyy-MM-dd HH:mm")
                    Write-RawResponse $stream 200 "text/html; charset=utf-8" $bytes @{
                        "Cache-Control"         = "no-cache"
                        "X-Dashboard-Generated" = $modified
                    }
                }
                $client.Close()
                continue
            }

            # GET /api/comments/{key}
            if ($method -eq "GET" -and $rawUrl -like "/api/comments/*") {
                $key = Get-IssueKey $rawUrl
                if (-not $key) {
                    Write-JsonResp $stream @{ error = "Invalid issue key" } 400
                    $client.Close()
                    continue
                }
                try {
                    Write-JsonResp $stream @{ comments = (Get-JiraComments $key) }
                } catch {
                    Write-Log "ERROR" "GET comments $key : $_"
                    Write-JsonResp $stream @{ error = "Jira error: $($_.Exception.Message)" } 502
                }
                $client.Close()
                continue
            }

            # POST /api/comments/{key}
            if ($method -eq "POST" -and $rawUrl -like "/api/comments/*" -and -not ($rawUrl -like "/api/comments/*/*")) {
                $key = Get-IssueKey $rawUrl
                if (-not $key) {
                    Write-JsonResp $stream @{ error = "Invalid issue key" } 400
                    $client.Close()
                    continue
                }
                try {
                    $payload = [Text.Encoding]::UTF8.GetString($req.BodyBytes) | ConvertFrom-Json
                    $text    = Invoke-Sanitize ([string]$payload.text)
                    if (-not $text) {
                        Write-JsonResp $stream @{ error = "Comment text is empty" } 400
                        $client.Close()
                        continue
                    }
                    $result  = Add-JiraComment $key $text
                    $created = if ($result.created) { [string]$result.created.Substring(0,10) } else { "" }
                    Write-Log "INFO" "Comment posted to $key : id=$($result.id)"
                    Write-JsonResp $stream @{ id = [string]$result.id; created = $created }
                } catch {
                    Write-Log "ERROR" "POST comment $key : $_"
                    Write-JsonResp $stream @{ error = "Server error: $($_.Exception.Message)" } 500
                }
                $client.Close()
                continue
            }

            # PUT /api/comments/{key}/{commentId}
            if ($method -eq "PUT" -and $rawUrl -like "/api/comments/*/*") {
                $key = Get-IssueKey $rawUrl
                $cid = Get-CommentId $rawUrl
                if (-not $key -or -not $cid) {
                    Write-JsonResp $stream @{ error = "Invalid issue key or comment id" } 400
                    $client.Close()
                    continue
                }
                try {
                    $payload = [Text.Encoding]::UTF8.GetString($req.BodyBytes) | ConvertFrom-Json
                    $text    = Invoke-Sanitize ([string]$payload.text)
                    if (-not $text) {
                        Write-JsonResp $stream @{ error = "Comment text is empty" } 400
                        $client.Close()
                        continue
                    }
                    $result = Update-JiraComment $key $cid $text
                    Write-Log "INFO" "Comment updated on $key : id=$cid"
                    Write-JsonResp $stream @{ id = $cid; updated = $true }
                } catch {
                    Write-Log "ERROR" "PUT comment $key/$cid : $_"
                    Write-JsonResp $stream @{ error = "Server error: $($_.Exception.Message)" } 500
                }
                $client.Close()
                continue
            }

            # DELETE /api/comments/{key}/{commentId}
            if ($method -eq "DELETE" -and $rawUrl -like "/api/comments/*/*") {
                $key = Get-IssueKey $rawUrl
                $cid = Get-CommentId $rawUrl
                if (-not $key -or -not $cid) {
                    Write-JsonResp $stream @{ error = "Invalid issue key or comment id" } 400
                    $client.Close()
                    continue
                }
                try {
                    Remove-JiraComment $key $cid
                    Write-Log "INFO" "Comment deleted on $key : id=$cid"
                    Write-JsonResp $stream @{ deleted = $true }
                } catch {
                    Write-Log "ERROR" "DELETE comment $key/$cid : $_"
                    Write-JsonResp $stream @{ error = "Server error: $($_.Exception.Message)" } 500
                }
                $client.Close()
                continue
            }

            # 404 fallthrough
            Write-ErrResp $stream 404 "Not found"
            $client.Close()

        } catch {
            Write-Log "ERROR" "Request handling error: $_"
            try { $client.Close() } catch {}
        }
    }
} finally {
    $tcp.Stop()
    Write-Log "INFO" "Server stopped."
}
