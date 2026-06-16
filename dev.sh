#!/bin/bash
set -e

trap 'kill 0' EXIT

ROOT="$(cd "$(dirname "$0")" && pwd)"

(cd "$ROOT/backend" && .venv/bin/python manage.py runserver) &
(cd "$ROOT/frontend" && npm install --silent && npm run dev) &

wait
