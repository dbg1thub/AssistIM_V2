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
- Compatibility routes for the current desktop client:
  - `POST /api/auth/refresh`
  - `POST /api/upload`
  - `WS /ws` (canonical chat websocket)
  - legacy chat websocket alias under `/ws/chat`
  - legacy chat aliases under `/api/chat/*`
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

5. Seed demo data if you want a non-empty local database:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/seed-data.ps1 -Reset
```

6. Start the API:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/run-api.ps1 -Reload
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
- private session creation and message read flow
- group permission and ownership transfer
- idempotent demo seed generation

## Demo seed data

`server/scripts/seed-data.ps1` writes a reusable local dataset. The seeded demo users are:

- `demo_alice`
- `demo_bob`
- `demo_carla`
- `demo_derek`

All demo users use the same password:

```text
Passw0rd!
```

The seed currently creates:

- 4 users
- 1 pending friend request
- 4 friendship rows
- 2 sessions
- 5 messages
- 1 group
- 2 moments
- 1 demo file record under `data/uploads/seed-demo-note.txt`

## Alternative without `.env`

If you do not want to create `server/.env` yet, `migrate.ps1`, `run-api.ps1`, and `seed-data.ps1` also accept explicit overrides:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/migrate.ps1 -DatabaseUrl "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/assistim"
powershell -ExecutionPolicy Bypass -File server/scripts/seed-data.ps1 -DatabaseUrl "postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/assistim" -Reset
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
python -m app.seed --reset
python -m pytest tests
```

## Environment

Copy `server/.env.postgres.example` to `server/.env` or pass `-DatabaseUrl` to the scripts.

## Notes

- Default development database is PostgreSQL.
- Native UUID columns are used through SQLAlchemy `Uuid`, which maps to PostgreSQL UUID natively.
- Uploaded files are stored under `data/uploads` and exposed at `/uploads/...`.
- For compatibility with the current desktop client, WebSocket payloads include both `type` and `event` style fields where useful.
- `/ws` is the canonical chat websocket endpoint; `/ws/chat` is kept as one explicit legacy alias.
- Message history pagination currently uses `before_id` by resolving the referenced message timestamp, because IDs are UUIDs rather than auto-increment integers.
- WebSocket incremental sync now filters messages by session membership instead of returning all recent messages globally.
- Legacy HTTP POST /api/chat/sync now mirrors the cursor-based replay model and returns both messages and events.
- Your PostgreSQL service was detected as `postgresql-x64-18`, and `server/scripts/init-postgres.ps1` can resolve `psql.exe` from that service path automatically.
