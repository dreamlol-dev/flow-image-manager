@echo off
REM ============================================================
REM  Flow Image Manager — Quick Launcher
REM  Double-click this file to start the application.
REM ============================================================

cd /d "%~dp0"

REM Detect Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python is not found on PATH.
    echo Please install Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Check for virtual environment
if exist ".venv\Scripts\python.exe" (
    echo Using virtual environment...
    call ".venv\Scripts\activate.bat"
) else (
    echo No virtual environment found. Using system Python.
    echo Tip: Create one with:  python -m venv .venv
)

REM Install / verify dependencies silently
python -m pip install -r requirements.txt --quiet

REM Launch
python main.py
pause

