#!/usr/bin/env sh
set -eu
command -v uv >/dev/null || { echo "Install uv first: https://docs.astral.sh/uv/"; exit 1; }
[ -f .env ] || { cp .env.example .env; echo "Created .env; set DJANGO_SECRET_KEY."; }
uv sync --extra dev
mkdir -p data
uv run python manage.py migrate
uv run python manage.py check
echo "Create the first manager with: uv run python manage.py createsuperuser"
