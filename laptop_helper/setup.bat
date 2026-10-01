@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Tally Parchi – Laptop Helper Setup
REM  Run this ONCE after installing Python 3.11+ from https://python.org
REM  Make sure Python is on your PATH (tick the checkbox during install).
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo ====================================================
echo  Tally Parchi – Laptop Helper Setup
echo ====================================================
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python not found on PATH.
    echo.
    echo  1. Download Python from https://python.org/downloads
    echo  2. Run the installer and TICK "Add Python to PATH"
    echo  3. Re-run this setup.bat
    echo.
    pause
    exit /b 1
)

echo Python found. Installing dependencies...
python -m pip install --upgrade pip
python -m pip install PyQt6 requests supabase python-dotenv

echo.
echo ====================================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Copy .env.example to .env
echo  2. Fill in your Supabase URL, key, and Tally company name
echo  3. Run schema.sql in your Supabase SQL Editor
echo  4. Run:  python main.py
echo ====================================================
echo.
pause
