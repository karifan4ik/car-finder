#!/usr/bin/env bash
# Запуск одной командой: ./run.sh
# Сам создаёт виртуальное окружение и ставит зависимости при первом запуске.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "Не найден файл .env. Скопируйте .env.example в .env и заполните ключи:"
    echo "  cp .env.example .env"
    exit 1
fi

if [ ! -d venv ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt
python3 -m car_finder.main
