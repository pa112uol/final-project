#!/bin/bash
set -e

trap 'kill 0' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -f "$ROOT/backend/.venv/bin/python" ]; then
  echo "[backend] Creating virtual environment..."
  python3 -m venv "$ROOT/backend/.venv"
  echo "[backend] Installing dependencies..."
  "$ROOT/backend/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt" --quiet
fi

(cd "$ROOT/backend" && .venv/bin/python manage.py runserver) &
(cd "$ROOT/frontend" && npm install --silent && npm run dev) &

wait
