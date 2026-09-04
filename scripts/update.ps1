$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force backups | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
if (Test-Path data/manager_suite.sqlite3) { Copy-Item data/manager_suite.sqlite3 "backups/manager_suite-$stamp.sqlite3" }
uv sync --locked
uv run python manage.py migrate
uv run python manage.py check
Write-Host 'Update complete. Restart the web service.'
