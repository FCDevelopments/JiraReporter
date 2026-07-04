@echo off
:: setup_network_server.bat
:: Run this ONCE as Administrator to enable the dashboard on the local network.
:: Right-click this file -> "Run as administrator"

echo.
echo ========================================================
echo  JiraReporter -- Network Dashboard Setup
echo ========================================================
echo.

:: Check for admin rights
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click the file and select "Run as administrator".
    pause
    exit /b 1
)

echo [1/3] Adding Windows Firewall rule for port 8080...
netsh advfirewall firewall delete rule name="JiraReporter Dashboard (8080)" >nul 2>&1
netsh advfirewall firewall add rule name="JiraReporter Dashboard (8080)" dir=in action=allow protocol=TCP localport=8080 profile=any
if %errorlevel% equ 0 (
    echo       OK
) else (
    echo       FAILED -- see error above
)

echo.
:: NOTE: Replace YOUR_USERNAME below with the Windows account that should run this task,
:: and update the python.exe / script paths to match your local install.
echo [2/3] Registering startup task (runs when YOUR_USERNAME logs in)...
schtasks /delete /tn "JiraReporter\DashboardServer" /f >nul 2>&1
schtasks /create /tn "JiraReporter\DashboardServer" /tr "\"C:\Path\To\Python\python.exe\" \"C:\Path\To\JiraReporter\serve_dashboard.py\"" /sc ONLOGON /ru "YOUR_USERNAME" /f
if %errorlevel% equ 0 (
    echo       OK
) else (
    echo       FAILED -- see error above
)

echo.
echo [3/3] Starting the server now (no reboot needed)...
schtasks /run /tn "JiraReporter\DashboardServer" >nul 2>&1
timeout /t 2 /nobreak >nul
netstat -ano | findstr ":8080" | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo       Server is listening on port 8080.
) else (
    echo       WARNING: Server may not have started yet -- check logs\dashboard_server.log
)

echo.
echo ========================================================
echo  Setup complete. Share this address with your team:
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set ip=%%a
    setlocal enabledelayedexpansion
    set ip=!ip: =!
    echo    http://!ip!:8080
    endlocal
)
echo.
echo  The dashboard refreshes every morning at 9:00 AM automatically.
echo ========================================================
echo.
pause
