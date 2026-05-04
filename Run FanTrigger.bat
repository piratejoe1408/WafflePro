@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FanTrigger - launcher

REM ============================================================
REM  Self-elevate to Administrator
REM ============================================================
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting Administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"

echo.
echo ============================================================
echo   FanTrigger - launcher
echo ============================================================
echo.

REM ============================================================
REM  Step 1 - Verify Python
REM ============================================================
echo [1/4] Checking Python...
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Run the diagnostic launcher first - it installs Python.
    pause
    exit /b 1
)
python --version

REM ============================================================
REM  Step 2 - Make sure dependencies are installed
REM ============================================================
echo.
echo [2/4] Installing/upgrading Python packages...
python -m pip install --upgrade pip --quiet
python -m pip install --quiet pythonnet pystray Pillow
if %errorlevel% neq 0 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)
echo Done.

REM ============================================================
REM  Step 3 - Make sure LibreHardwareMonitorLib.dll is present
REM ============================================================
echo.
echo [3/4] Checking LibreHardwareMonitorLib.dll...
if exist "LibreHardwareMonitorLib.dll" (
    echo Already present.
) else (
    echo Downloading from NuGet...
    powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; $ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.nuget.org/api/v2/package/LibreHardwareMonitorLib/0.9.4' -OutFile 'lhm.zip'"
    if !errorlevel! neq 0 (
        echo Download failed.
        pause
        exit /b 1
    )
    powershell -NoProfile -Command "Expand-Archive -Path 'lhm.zip' -DestinationPath 'lhm_extract' -Force"
    if exist "lhm_extract\lib\net472\LibreHardwareMonitorLib.dll" (
        copy /y "lhm_extract\lib\net472\LibreHardwareMonitorLib.dll" "LibreHardwareMonitorLib.dll" >nul
    ) else (
        echo Could not find LibreHardwareMonitorLib.dll inside the package.
        pause
        exit /b 1
    )
    rmdir /s /q lhm_extract >nul 2>&1
    del /q lhm.zip >nul 2>&1
)

REM ============================================================
REM  Step 4 - Find pythonw.exe and launch in the background
REM ============================================================
echo.
echo [4/4] Launching FanTrigger in the background...

set "PYTHONW="
for /f "delims=" %%i in ('where pythonw 2^>nul') do (
    if not defined PYTHONW set "PYTHONW=%%i"
)
if not defined PYTHONW (
    echo Could not find pythonw.exe. Falling back to python.exe.
    set "PYTHONW=python"
)

start "" "!PYTHONW!" "%~dp0fan_trigger.py"

echo.
echo FanTrigger is now running in the system tray.
echo Look for the colored icon (number = current CPU temp).
echo Right-click it for the menu.
echo.
echo This window will close in 5 seconds.
timeout /t 5 >nul
endlocal
