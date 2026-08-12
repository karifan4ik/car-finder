@echo off
REM Запуск одной командой на Windows: дважды щёлкните этот файл,
REM или наберите run.bat в PowerShell/cmd, находясь в этой папке.
cd /d "%~dp0"

if not exist .env (
    echo Не найден файл .env. Скопируйте .env.example в .env и заполните ключи.
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
