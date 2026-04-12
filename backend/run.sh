#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Создаю виртуальное окружение .venv …"
  python3 -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate

pip install -q -r requirements.txt

echo "Запуск API и интерфейса: http://127.0.0.1:8000 и http://localhost:8000"
echo "Логин: admin@edda.local  Пароль: Admin123!"
# «::» — типичный сокет IPv6 на macOS/Linux: браузер часто ходит на localhost как ::1; при только 127.0.0.1 получался «Failed to fetch».
# Если на вашей системе uvicorn с :: не стартует — замените на: --host 0.0.0.0
exec uvicorn app.main:app --host '::' --port 8000
