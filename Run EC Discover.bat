@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FanTrigger - EC discovery

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
echo   FanTrigger - EC register discovery
echo ============================================================
echo.
echo The replay tests proved that MSI Center filters out software-
echo injected keystrokes. We now bypass the keyboard entirely and
echo write to the embedded controller (EC) directly via the WinRing0
echo driver that LibreHardwareMonitor already loaded.
echo.
echo This script ONLY READS the EC during discovery. It does not
echo change any settings. At the very end it offers an OPTIONAL
echo verification write that you can decline.
echo.
echo What you'll do:
echo   - we snapshot EC RAM
echo   - you press FN+UpArrow ONCE to toggle Cooler Boost
echo   - we snapshot again
echo   - repeat 4 times total
echo   - we identify the byte that flips with state
echo.
echo Have your laptop with Cooler Boost OFF (normal idle fans) before
echo we begin. Make sure MSI Center is open as usual.
echo.
pause

REM Make sure prerequisites are present (LHM DLL + pythonnet)
if not exist "LibreHardwareMonitorLib.dll" (
    echo.
    echo LibreHardwareMonitorLib.dll missing - run "Run FanTrigger.bat" once first.
    pause
    exit /b 1
)
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo Python not found - run "Run Diagnostic.bat" once first.
    pause
    exit /b 1
)
python -c "import clr" 2>nul
if %errorlevel% neq 0 (
    echo Installing pythonnet...
    python -m pip install --quiet pythonnet
)

echo.
python ec_discover.py
echo.
pause
endlocal
