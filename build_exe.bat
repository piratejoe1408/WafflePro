@echo off
setlocal EnableExtensions
title WafflePro - build .exe

cd /d "%~dp0"

echo.
echo ============================================================
echo   WafflePro - PyInstaller build
echo ============================================================
echo.
echo Bakes fan_trigger.py + ec_control.py + their Python dependencies
echo into a single WafflePro.exe so end users don't need Python
echo installed. Output: dist\WafflePro.exe
echo.
echo Note: the .exe still expects LibreHardwareMonitorLib.dll next to
echo it at runtime. For distribution, zip the .exe and the DLL together.
echo.
pause

where python >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo ERROR: Python is not in PATH. Install it first ^(see Run FanTrigger.bat^).
    pause
    exit /b 1
)
python --version

echo.
echo Installing build + runtime dependencies...
python -m pip install --quiet --upgrade pip
python -m pip install --quiet pyinstaller pythonnet pystray Pillow
if %errorlevel% neq 0 (
    echo pip install failed.
    pause
    exit /b 1
)

echo.
echo Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
if exist WafflePro.spec del /q WafflePro.spec

echo.
echo Building WafflePro.exe (this can take a couple of minutes)...
python -m PyInstaller ^
    --onefile ^
    --noconsole ^
    --name WafflePro ^
    --hidden-import pystray._win32 ^
    --collect-submodules pythonnet ^
    fan_trigger.py
if %errorlevel% neq 0 (
    echo.
    echo Build failed - scroll up for the PyInstaller error.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Build complete
echo ============================================================
echo.
echo Built: %CD%\dist\WafflePro.exe
echo.
echo To run / distribute:
echo   1. Copy dist\WafflePro.exe to the target machine.
echo   2. Copy LibreHardwareMonitorLib.dll into the SAME folder.
echo   3. Right-click WafflePro.exe -^> Run as administrator.
echo.
echo (For a clean release zip: take the .exe + the DLL + README.md
echo and zip them together. That's all an end user needs.)
echo.
pause
endlocal
