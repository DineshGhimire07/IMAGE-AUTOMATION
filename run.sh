#!/usr/bin/env bash
# ========================================================
#  XINVORA AI STUDIO - macOS / Linux Launcher
# ========================================================

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
    echo "[ERROR] Virtual environment (.venv) not found!"
    echo "Please create .venv and install dependencies first."
    exit 1
fi

source .venv/bin/activate
exec python main.py
