@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FanTrigger - install autostart

REM Self-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo ============================================================
echo   FanTrigger - install autostart
echo ============================================================
echo.
echo This creates a Windows scheduled task called "FanTrigger" that
echo runs the utility automatically every time you log in to Windows,
echo with Administrator privileges (needed for sensors and keystrokes).
echo.
echo You can remove it at any time by running "Uninstall Autostart.bat".
echo.
pause

REM Find pythonw.exe
set "PYTHONW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%i"
)
if not defined PYTHONW (
    echo ERROR: pythonw.exe not found in PATH.
    echo Run "Run FanTrigger.bat" once first.
    pause
    exit /b 1
)

set "SCRIPT=%~dp0fan_trigger.py"

echo Using pythonw: !PYTHONW!
echo Script:        !SCRIPT!
echo.

REM Create the task. /RL HIGHEST = run with admin rights.
REM /SC ONLOGON   = trigger on user logon.
REM /F            = overwrite if it already exists.
schtasks /Create /TN "FanTrigger" ^
    /TR "\"!PYTHONW!\" \"!SCRIPT!\"" ^
    /SC ONLOGON ^
    /RL HIGHEST ^
    /F

if %errorlevel% neq 0 (
    echo.
    echo ERROR: schtasks failed.
    pause
    exit /b 1
)

echo.
echo Done. FanTrigger will start automatically next time you log in.
echo To start it right now without rebooting, use "Run FanTrigger.bat".
echo.
pause
endlocal
