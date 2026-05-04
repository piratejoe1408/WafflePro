@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FanTrigger - Diagnostic v2

REM Self-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo ============================================================
echo   FanTrigger - Diagnostic v2
echo ============================================================
echo.
echo This v2 captures FULL keyboard event details (vkCode, scanCode,
echo flags) using the raw Windows hook directly, then tries six
echo different replay strategies so we can find which one (if any)
echo MSI Center accepts.
echo.
echo IMPORTANT: After Part A starts, press FN + UpArrow several
echo times AND VERIFY THE FANS RESPOND each time. We need to confirm
echo the hand-press actually toggles boost before we trust the data.
echo.
pause

REM No external dependencies needed - v2 uses only ctypes (built into Python).
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not in PATH. Run "Run Diagnostic.bat" first.
    pause
    exit /b 1
)
python --version

echo.
echo Launching diagnostic v2...
echo.
python fan_diagnostic_v2.py

echo.
pause
endlocal
