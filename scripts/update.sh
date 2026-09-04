#!/usr/bin/env sh
set -eu
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
[ ! -f data/manager_suite.sqlite3 ] || cp data/manager_suite.sqlite3 "backups/manager_suite-$stamp.sqlite3"
uv sync --locked
uv run python manage.py migrate
uv run python manage.py check
echo "Update complete. Restart the web service."
