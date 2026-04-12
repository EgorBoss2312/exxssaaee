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

echo "Запуск API и интерфейса на http://127.0.0.1:8000"
echo "Логин: admin@edda.local  Пароль: Admin123!"
exec uvicorn app.main:app --host 127.0.0.1 --port 8000
