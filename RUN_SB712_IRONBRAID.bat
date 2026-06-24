@echo off
:: RUN_SB712_IRONBRAID.bat
:: Windows launcher for SB-712 IronBraid Radiant Core
::
:: Prerequisites: Python 3.9+ installed and on PATH
::
:: Usage: double-click or run from a command prompt in the repo root.

setlocal enabledelayedexpansion

echo ============================================================
echo   SB-712 IronBraid Radiant Core - Windows Launcher
echo ============================================================
echo.

:: Check Python is available.
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo Please install Python 3.9+ from https://python.org and retry.
    pause
    exit /b 1
)

:: Show Python version for diagnostics.
echo Python version:
python --version
echo.

:: Run the entrypoint.
python "%~dp0run_sb712_ironbraid.py"
if errorlevel 1 (
    echo.
    echo ERROR: Entrypoint exited with a non-zero status.
    pause
    exit /b 1
)

echo.
echo Done. Press any key to close.
pause >nul
exit /b 0
