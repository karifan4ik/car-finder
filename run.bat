@echo off
REM One-click launch on Windows: double-click this file, or run
REM run.bat from PowerShell/cmd while inside this folder.
REM Messages below are in English on purpose - Windows console often
REM shows Cyrillic text as garbled characters (encoding issue), so
REM plain English here avoids that. The actual car listings sent to
REM Telegram are still fully in Russian.
cd /d "%~dp0"

if not exist .env (
    echo No .env file found in this folder.
    echo Copy .env.example to .env and fill in your keys, then run this again.
    echo See README.md, step 4, for how to do this.
    pause
    exit /b 1
)

if not exist venv (
    python -m venv venv
)

call venv\Scripts\activate.bat
pip install -q -r requirements.txt
python -m car_finder.main

pause
