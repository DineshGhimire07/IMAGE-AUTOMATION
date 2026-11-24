@echo off
setlocal enabledelayedexpansion

REM ========================================================
REM  XINVORA AI STUDIO - Windows Launcher
REM ========================================================

REM Change to script directory
cd /d "%~dp0"

echo ========================================================
echo  Launching XINVORA AI Studio...
echo ========================================================

REM Check if Python is installed on system
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not added to PATH!
    echo Please install Python (3.11 or 3.12 recommended) from:
    echo   https://www.python.org/downloads/
    echo *IMPORTANT*: Check "Add python.exe to PATH" during installation!
    pause
    exit /b 1
)

REM If virtual environment does not exist, set it up automatically on first run
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo [SETUP] First-time setup detected. Configuring environment...
    echo [1/3] Creating virtual environment (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create .venv.
        pause
        exit /b 1
    )

    echo [2/3] Installing required packages from requirements.txt...
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )

    echo [3/3] Installing Playwright Chromium browser...
    python -m playwright install chromium
    echo.
    echo [SETUP COMPLETE] Environment configured successfully!
    echo.
) else (
    call .venv\Scripts\activate.bat
)

REM Launch Main Application
echo Starting main application...
python main.py

REM Keep window open if application exited with an error
if errorlevel 1 (
    echo.
    echo ========================================================
    echo  Application terminated with error code !errorlevel!
    echo ========================================================
    pause
)
