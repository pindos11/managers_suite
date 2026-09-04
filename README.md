# Manager's Suite

Manager dashboard for rostering, performance reporting and alerts.

## Quick start

Windows: run `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`.

macOS/Linux: run `sh scripts/setup.sh`.

Then create the manager account (`uv run python manage.py createsuperuser`), start the UI (`uv run python manage.py runserver`), and open `http://127.0.0.1:8000/`. Configure employees, eligible locations and published shift assignments. Dates and shift times are displayed in `BUSINESS_TIME_ZONE` (default: `Europe/Kyiv`), while timestamps remain UTC in the database.

## Operations

Run `uv run pytest` for automated checks. `GET /health/` verifies database connectivity. Keep `.env`, `data/`, and backups outside Git. For production network access, bind behind HTTPS and replace the development secret.

For manual roster testing, first create an active location, then run `uv run python manage.py seed_test_employees --count 12`. It adds clearly marked `[TEST]` employees, assigns them to all active locations, and never changes existing employees.

## GitHub handoff

The repository is safe to publish as long as `.env`, `data/`, backups and other ignored files remain untracked. Copy `.env.example` to `.env` for each environment and set a unique `DJANGO_SECRET_KEY`; do not reuse the example value in production. GitHub Actions runs Django's system checks and the test suite for every push and pull request.

To publish an initialized local repository, create an empty GitHub repository and add it as `origin`, then push the default branch:

```sh
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin main
```
