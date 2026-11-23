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

REM Check if virtual environment exists
if not exist ".venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment (.venv) was not found!
    echo Please run the following setup commands:
    echo   python -m venv .venv
    echo   .venv\Scripts\activate
    echo   pip install -r requirements.txt
    echo   python -m playwright install chromium
    pause
    exit /b 1
)

REM Activate virtual environment
call .venv\Scripts\activate.bat

REM Verify python interpreter in venv
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python failed to initialize from virtual environment.
    pause
    exit /b 1
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
