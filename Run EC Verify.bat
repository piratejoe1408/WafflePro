@echo off
setlocal EnableExtensions
title FanTrigger - EC verify

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
echo   FanTrigger - EC verification
echo ============================================================
echo.
echo Quick test of register 0x98 bit 7 (the Cooler Boost bit we
echo discovered). It will:
echo   1. Read the current value of register 0x98
echo   2. Set bit 7 - boost should go ON, fans LOUD (5s)
echo   3. Clear bit 7 - boost should go OFF, fans QUIET (5s)
echo   4. Restore the original value and exit
echo.
echo Just listen. Use your ears as the verdict.
echo.
pause

python ec_verify.py
echo.
pause
endlocal
