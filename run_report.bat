@echo off
setlocal

:: NOTE: Update PYTHON and SCRIPT_DIR below to match your local install path.
set PYTHON=C:\Path\To\Python\python.exe
set SCRIPT_DIR=C:\Path\To\JiraReporter
set LOG_DIR=%SCRIPT_DIR%\logs

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

:: Timestamped log file for this run
for /f "tokens=1-6 delims=/:. " %%a in ("%date% %time%") do (
    set LOGFILE=%LOG_DIR%\run_%%d-%%a-%%b_%%c%%e%%f.log
)

echo ============================================================ >> "%LOGFILE%"
echo JiraReporter run started: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

:: Step 1 ? fetch data from Jira via PowerShell (bypasses Defender HTTP behavioral rules)
echo [1/3] Running jira_fetcher.ps1... >> "%LOGFILE%"
powershell.exe -NonInteractive -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\jira_fetcher.ps1" >> "%LOGFILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: jira_fetcher.ps1 failed with exit code %ERRORLEVEL% >> "%LOGFILE%"
    echo Run aborted. >> "%LOGFILE%"
    exit /b %ERRORLEVEL%
)

:: Step 2 ? generate HTML dashboard
echo [2/3] Running jira_report_visualizer.py... >> "%LOGFILE%"
"%PYTHON%" -u "%SCRIPT_DIR%\jira_report_visualizer.py" >> "%LOGFILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: jira_report_visualizer.py failed with exit code %ERRORLEVEL% >> "%LOGFILE%"
    echo Run aborted. >> "%LOGFILE%"
    exit /b %ERRORLEVEL%
)

:: Step 2b ? copy dashboard to a shared location for company-wide sharing (e.g. OneDrive/SharePoint)
:: NOTE: Update this path to your own shared drive/folder.
set ONEDRIVE_DEST=C:\Path\To\Shared\IT Reports\jira_report.html
echo [2b] Copying dashboard to shared location... >> "%LOGFILE%"
copy /y "%SCRIPT_DIR%\jira_report.html" "%ONEDRIVE_DEST%" >> "%LOGFILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo WARNING: shared-location copy failed -- dashboard still available locally. >> "%LOGFILE%"
)

:: Step 3 ? send email digest
echo [3/3] Running jira_emailer.py... >> "%LOGFILE%"
"%PYTHON%" -u "%SCRIPT_DIR%\jira_emailer.py" >> "%LOGFILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: jira_emailer.py failed with exit code %ERRORLEVEL% >> "%LOGFILE%"
    echo Run aborted. >> "%LOGFILE%"
    exit /b %ERRORLEVEL%
)

echo ============================================================ >> "%LOGFILE%"
echo JiraReporter run completed successfully: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
exit /b 0
