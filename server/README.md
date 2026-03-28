# AssistIM Backend

## What is included

This backend implements the sections 1-127 from `backend_architecture.md`:

- FastAPI app entrypoint
- Core/config/database/security/logging modules
- API routers for auth, users, friends, sessions, messages, groups, moments, files
- Repository and service layers
- WebSocket endpoints for chat and presence
- Unified API response format
- JWT auth, password hashing, request logging, basic rate limiting, file upload
- Database schema layer aligned to sections 27-47
- Alembic bootstrap and initial migration
- Current client-facing compatibility routes:
  - `POST /api/v1/auth/refresh`
  - `POST /api/v1/files/upload`
  - `WS /ws` (canonical chat websocket)

## Recommended local setup on Windows

1. Copy `server/.env.postgres.example` to `server/.env` and replace `YOUR_PASSWORD`.
2. Create a local virtual environment and install backend dependencies:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/install-deps.ps1
```

3. Create the PostgreSQL database if it does not exist yet:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/init-postgres.ps1
```

4. Run migrations:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/migrate.ps1
```

5. Start the API:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/run-api.ps1 -Reload
```

6. Create test accounts manually from the desktop client or with `POST /api/v1/auth/register`.

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/auth/register" `
  -ContentType "application/json" `
  -Body (@{
    username = "alice"
    password = "Passw0rd!"
    nickname = "Alice"
  } | ConvertTo-Json)
```

The scripts automatically prefer `server/.venv/Scripts/python.exe` when present.

## Tests

Run the backend integration tests with:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/test.ps1 -VerboseOutput
```

The current test suite covers:

- auth register/login/refresh/me
- friend request accept flow
- direct session creation and message read flow
- group permission and ownership transfer

## Creating test accounts

The backend no longer ships a demo seed path. This keeps local development on the same code path as production and avoids a second, schema-sensitive data writer.

Use the desktop client to register users normally, or create them over HTTP:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/auth/register" `
  -ContentType "application/json" `
  -Body (@{
    username = "bob"
    password = "Passw0rd!"
    nickname = "Bob"
  } | ConvertTo-Json)
```

After registration, use the normal client flows to add friends, create direct sessions, create groups, and upload files.

## Alternative without `.env`

If you do not want to create `server/.env` yet, `migrate.ps1` and `run-api.ps1` accept explicit overrides:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/migrate.ps1 -DatabaseUrl "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/assistim"
powershell -ExecutionPolicy Bypass -File server/scripts/run-api.ps1 -DatabaseUrl "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/assistim" -Reload
```

## Manual run

From repository root:

```bash
python -m uvicorn app.main:app --app-dir server --reload --host 0.0.0.0 --port 8000
```

From `server/`:

```bash
python -m alembic upgrade head
python -m pytest tests
```

## Environment

Copy `server/.env.postgres.example` to `server/.env` or pass `-DatabaseUrl` to the scripts.

## Notes

- Default development database is PostgreSQL.
- Native UUID columns are used through SQLAlchemy `Uuid`, which maps to PostgreSQL UUID natively.
- Uploaded files are stored under `data/uploads` and exposed at `/uploads/...`.
- WebSocket payloads use the canonical `type` field for realtime events.
- Message history uses the session-scoped `/api/v1/sessions/{session_id}/messages` endpoint with an optional `before` timestamp cursor.
- WebSocket incremental sync now filters messages by session membership instead of returning all recent messages globally.
- Your PostgreSQL service was detected as `postgresql-x64-18`, and `server/scripts/init-postgres.ps1` can resolve `psql.exe` from that service path automatically.

