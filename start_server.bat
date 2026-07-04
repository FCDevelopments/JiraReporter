@echo off
:: Jira Dashboard Server Launcher
:: Double-click to start the server in the background (no admin needed).
:: The server runs hidden and logs to C:\JiraReporter\logs\dashboard_server.log

:: Check if already running on port 8080
netstat -ano | findstr ":8080 " | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
    echo Server is already running on port 8080.
    timeout /t 3 >nul
    exit /b 0
)

:: Start server as a hidden background process (no admin required)
powershell.exe -ExecutionPolicy Bypass -NoProfile -Command ^
    "Start-Process powershell.exe -ArgumentList '-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File ""C:\JiraReporter\serve_dashboard.ps1""' -WindowStyle Hidden"

echo Jira Dashboard Server started.
echo Access it at: http://localhost:8080
echo Log file: C:\JiraReporter\logs\dashboard_server.log
timeout /t 4 >nul
