@echo off
setlocal EnableExtensions
title FanTrigger - uninstall autostart

REM Self-elevate
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ============================================================
echo   FanTrigger - uninstall autostart
echo ============================================================
echo.
echo This removes the "FanTrigger" scheduled task. The utility will
echo NOT auto-start at login any more. (You can still launch it
echo manually via "Run FanTrigger.bat" whenever you want.)
echo.
pause

schtasks /Delete /TN "FanTrigger" /F
if %errorlevel% neq 0 (
    echo.
    echo No task named "FanTrigger" was found, or schtasks failed.
    echo Nothing to do.
)

echo.
pause
endlocal
