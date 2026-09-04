$ErrorActionPreference = 'Stop'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv first: https://docs.astral.sh/uv/' }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host 'Created .env; set DJANGO_SECRET_KEY.' }
uv sync --extra dev
New-Item -ItemType Directory -Force data | Out-Null
uv run python manage.py migrate
uv run python manage.py check
Write-Host 'Create the first manager with: uv run python manage.py createsuperuser'
