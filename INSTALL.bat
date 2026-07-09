@echo off
:: INSTALL.bat — SB-712 IronBraid Radiant Core
:: One-click installer for Windows 10 / Python 3.10+
::
:: INSTRUCTIONS:
::   1. Install Python 3.10+ from https://python.org
::      (tick "Add Python to PATH" during install)
::   2. Double-click this file.
::   3. When it finishes, run RUN_SB712_IRONBRAID.bat to start the system.

setlocal enabledelayedexpansion

echo ============================================================
echo   SB-712 IronBraid Radiant Core — INSTALLER
echo ============================================================
echo.

:: ── 1. Verify Python ──────────────────────────────────────────
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    echo.
    echo  Please install Python 3.10+ from https://python.org
    echo  Make sure to tick "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo Found: %PY_VER%
echo.

:: ── 2. Upgrade pip ────────────────────────────────────────────
echo [1/4] Upgrading pip...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo WARNING: Could not upgrade pip. Continuing with existing version.
)
echo       Done.
echo.

:: ── 3. Install Python package (editable + dev extras) ─────────
echo [2/4] Installing SB-712 + SB688 Python packages...
python -m pip install -e "%~dp0.[dev]"
if errorlevel 1 (
    echo.
    echo ERROR: Package installation failed. See output above.
    pause
    exit /b 1
)
echo       Done.
echo.

:: ── 4. Verify all imports resolve ─────────────────────────────
echo [3/4] Verifying package imports...
python -c "import sb688, stitch_brick, sb_712, sb_712.security, sb_712.service_host, intelligence.vera_gate, recovery.phoenix_triangle; print('  All imports OK')"
if errorlevel 1 (
    echo.
    echo ERROR: Import verification failed. See output above.
    pause
    exit /b 1
)
echo.

:: ── 5. Run test suite ─────────────────────────────────────────
echo [4/5] Running test suite (418 tests expected)...
python -m pytest tests\ -q --tb=short
if errorlevel 1 (
    echo.
    echo WARNING: Some tests failed. Review output above before deploying.
    echo          The system may still be partially functional.
    pause
) else (
    echo.
    echo  All tests passed.
)
echo.

:: ── 6. Register watchdog scheduled task (optional) ────────────
echo [5/5] Registering SB712 watchdog startup task...
if exist "%~dp0sb712_watchdog.py" (
    schtasks /query /tn "SB712Watchdog" >nul 2>&1
    if not errorlevel 1 (
        schtasks /delete /tn "SB712Watchdog" /f >nul 2>&1
    )
    schtasks /create /tn "SB712Watchdog" /sc onlogon /rl LIMITED /tr "\"python\" \"%~dp0sb712_watchdog.py\"" /f >nul 2>&1
    if errorlevel 1 (
        echo WARNING: Could not register scheduled task automatically.
        echo          You can run manually:
        echo          schtasks /create /tn "SB712Watchdog" /sc onlogon /rl LIMITED /tr "\"python\" \"%~dp0sb712_watchdog.py\"" /f
    ) else (
        echo       Watchdog task 'SB712Watchdog' registered.
    )
) else (
    echo WARNING: sb712_watchdog.py not found; skipping watchdog task setup.
)
echo.

:: ── Done ──────────────────────────────────────────────────────
echo ============================================================
echo   INSTALLATION COMPLETE
echo ============================================================
echo.
echo  Next steps:
echo    1. Copy .env.example to .env and fill in your secrets.
echo       (Required for JWT auth and Supabase integration)
echo.
echo    2. Double-click  RUN_SB712_IRONBRAID.bat  to run a
echo       full integrity scan and generate your first report.
echo.
echo    3. Watchdog starts automatically at sign-in via Task Scheduler:
echo       Task name: SB712Watchdog
echo       Manual run: python sb712_watchdog.py
echo.
echo    4. Optional — Windows service install (run as Admin):
echo       powershell -ExecutionPolicy Bypass -File scripts\install-sb712-service.ps1
echo.
echo    5. Optional — Control Room UI:
echo       python -m http.server 8080 --directory ui
echo       Then open  http://localhost:8080  in a browser.
echo.
echo    6. Optional — run the validation framework:
echo       python run_validation.py --tests 100 --scenario byte_corruption
echo.
pause
exit /b 0
