# Resume & Career Guidance Platform

A modular Flask application for resume analysis, career guidance, learning plans,
job matching, resume improvement, and interview practice. AI features use a
server-side Gemini integration; the browser never receives provider credentials.

## Status

Implemented: responsive UI and authentication; private PDF/DOCX resume analysis;
token controls and usage reporting; career roadmaps and learning-resource
progress; Adzuna search and job matching; editable resume drafts and DOCX export;
interview practice; and an admin dashboard. Production deployment still requires
provider credentials and deployment-specific hardening. No mock AI results or
fabricated job listings are used.

## Requirements

- Python 3.11 or newer
- Git
- A Gemini API key for AI-backed features (configure locally; do not commit it)

## Local setup (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Generate a unique secret with `py -c "import secrets; print(secrets.token_hex(32))"`
and set `SECRET_KEY` in `.env`. Add `GEMINI_API_KEY` to enable AI-backed features.
The default database is SQLite under `instance`. Local uploads and database files
are excluded from version control.

Apply the checked-in database migrations:

```powershell
flask --app run.py db upgrade
```

When changing models, generate and review a migration with
`flask --app run.py db migrate -m "describe change"` before applying it.

After migrations are applied, verify and seed the official learning-resource
catalog. This command makes outbound HTTPS requests only to the catalog's
allow-listed provider domains; links that fail verification remain non-clickable.

```powershell
flask --app run.py seed-learning-resources
```

After registering the intended administrator account, promote it from the
server shell:

```powershell
flask --app run.py make-admin admin@example.com
```

Registration always creates a regular user; administrator privileges are not
self-selectable. The admin page can change runtime AI usage limits but never
shows provider credentials.

Job search uses the Adzuna Search API for India. Register with Adzuna and put the
issued `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in `.env`. Search results are fetched
live, are not cached by this app, and keep the provider's application redirect
and attribution. Review Adzuna's current API terms and access limits before
deployment. Official API documentation: <https://developer.adzuna.com/overview>
and <https://developer.adzuna.com/docs/search>.

For PostgreSQL, install `psycopg[binary]` and set `DATABASE_URL`, for example
`postgresql+psycopg://user:password@host:5432/database`.

## Run

```powershell
python run.py
```

## Test

```powershell
pytest
```

AI tests use service doubles and do not call Gemini. To exercise live AI features,
provide a valid key locally; never place it in frontend code or commit it.

For production, configure a shared rate-limit backend such as Redis with
`RATELIMIT_STORAGE_URI`; `memory://` is for local development only.

## Security notes

- Keep `.env`, uploaded documents, and local database files private.
- Use a unique `SECRET_KEY`; the application refuses to start with the example placeholder.
- Set `SESSION_COOKIE_SECURE=true` when serving over HTTPS in production.
- Configure secrets through the production hosting provider's secret manager.
- Resume upload has size/page/text limits. Files are stored outside the static web root.
- The resume compatibility assessment is informational and is not a guaranteed
  score from any employer's applicant tracking system.
- Usage token counts are not a fixed estimate of API cost.
- Resource links are restricted to curated HTTPS domains and are enabled only while
  their verification is recent.
- Job listings are provider-sourced; provider credentials remain server-side, results
  are not persisted, and an unavailable provider yields an error rather than sample data.
