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

## Cloud test deployment

For the first shared test build, deploy the backend on one cloud server and package the Windows client with the server address written into `data/config.json`.

Use:

- `server/Dockerfile`, `server/.dockerignore`, and `deploy/docker/docker-compose.yml` for the Docker Compose deployment path
- `deploy/docker/server.env.example` as the Docker env template; set the database password by editing `POSTGRES_PASSWORD` in that file
- `server/.env.production.example` as the production environment template
- `docs/deployment/test_release_deploy.md` for Ubuntu + PostgreSQL + Nginx + systemd deployment steps
- `deploy/server/assistim-api.service.example` and `deploy/server/nginx-assistim.conf.example` as server config templates
- `tools/build_client_nuitka.ps1` for the Windows client package

The client package intentionally excludes local model weight files such as `.gguf`; model files should be distributed separately when AI features need to be tested.

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

## Development diagnostics dashboard

The backend exposes a read-only diagnostics endpoint for development and test
verification. It is disabled by default and requires an authenticated admin user.

Run migrations before enabling the dashboard after pulling this feature:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/migrate.ps1
```

Create the first admin from the server machine:

```powershell
powershell -ExecutionPolicy Bypass -File server/scripts/set-admin.ps1 -Username test1
```

Enable it only in a local or controlled test environment:

```powershell
$env:ADMIN_DASHBOARD_ENABLED = "true"
powershell -ExecutionPolicy Bypass -File server/scripts/run-api.ps1 -Reload
```

Request:

```powershell
$token = "<access_token>"
Invoke-RestMethod -Method Get `
  -Uri "http://127.0.0.1:8000/api/v1/admin/dashboard" `
  -Headers @{ Authorization = "Bearer $token" }
```

The dashboard endpoint reports backend runtime, database, users, contacts, sessions,
messages, groups, moments, files, WebSocket, active calls, E2EE key inventory,
admin audit counts, recent HTTP requests, and recent warning/error logs. It
does not expose private keys or provide any write operation.

The same admin role also unlocks backend-only user-management APIs:

- `GET /api/v1/admin/audit-logs`: list audit logs with `actor_username`, `action`, `target_type`, `target_id`, `success`, `created_from`, `created_to`, `page`, and `size` filters.
- `GET /api/v1/admin/audit-logs/{log_id}`: inspect one audit log.
- `GET /api/v1/admin/logs/files`: list server log files under the configured log directory.
- `GET /api/v1/admin/logs`: query sanitized server log entries with `file_name`, `level`, `keyword`, `created_from`, `created_to`, and `limit` filters.
- `GET /api/v1/admin/logs/files/{file_name}/download`: download one sanitized server log file as a text attachment.
- `GET /api/v1/admin/files/storage/status`: inspect local upload storage database/disk consistency summary.
- `GET /api/v1/admin/files/storage/issues`: list missing disk files, orphan disk files, invalid storage keys, and metadata mismatches.
- `GET /api/v1/admin/chat/sessions`: list chat sessions with `type`, `keyword`, `user_id`, `page`, and `size` filters.
- `GET /api/v1/admin/chat/sessions/{session_id}`: inspect one chat session, including members, counters, encryption mode, and the latest message.
- `GET /api/v1/admin/chat/sessions/{session_id}/messages`: inspect one session's messages with `type`, `page`, and `size` filters.
- `GET /api/v1/admin/chat/health`: inspect chat data consistency issues such as orphan messages, missing members, `session_seq` gaps or duplicates, and `last_message_seq` drift.
- `GET /api/v1/admin/contacts/friend-requests`: list friend requests with `status`, `sender_id`, `receiver_id`, `page`, and `size` filters.
- `GET /api/v1/admin/contacts/friendships`: list friendship rows with `user_id`, `friend_id`, `page`, and `size` filters.
- `GET /api/v1/admin/contacts/health`: inspect contact data consistency issues such as one-way friendships, self-friend rows, missing users, duplicate requests, and invalid request statuses.
- `GET /api/v1/admin/groups`: list groups with `keyword`, `owner_id`, `page`, and `size` filters.
- `GET /api/v1/admin/groups/{group_id}`: inspect one group, including owner, session, members, announcement, and avatar metadata.
- `GET /api/v1/admin/groups/{group_id}/members`: inspect group members with `role`, `user_id`, `page`, and `size` filters.
- `GET /api/v1/admin/groups/health`: inspect group data consistency issues such as missing sessions, invalid session type, missing owners, owner/member drift, group/session member drift, invalid announcement messages, and missing avatar file records.
- `GET /api/v1/admin/moments`: list moments with `keyword`, `user_id`, `page`, and `size` filters.
- `GET /api/v1/admin/moments/{moment_id}`: inspect one moment, including author, content, and interaction counts.
- `GET /api/v1/admin/moments/{moment_id}/comments`: inspect moment comments with `user_id`, `page`, and `size` filters.
- `GET /api/v1/admin/moments/{moment_id}/likes`: inspect moment likes with `user_id`, `page`, and `size` filters.
- `GET /api/v1/admin/moments/health`: inspect moment data consistency issues such as missing authors, orphan comments, orphan likes, missing interaction users, and duplicate like rows.
- `GET /api/v1/admin/realtime/connections`: inspect currently bound WebSocket users and connection records with an optional `user_id` filter.
- `GET /api/v1/admin/realtime/health`: inspect realtime connection integrity issues such as missing users, unbound raw sockets, and bound records without live sockets.
- `GET /api/v1/admin/calls/active`: inspect active in-memory private calls with an optional `user_id` filter.
- `GET /api/v1/admin/calls/health`: inspect active-call registry issues such as missing sessions, invalid session type, missing users, non-member participants, invalid statuses, and user-to-call mapping drift.
- `GET /api/v1/admin/http/requests`: inspect recent in-process HTTP request diagnostics with `method`, `path_contains`, `status_code`, `user_id`, and `limit` filters.
- `GET /api/v1/admin/http/health`: inspect HTTP request health signals such as error responses, 5xx responses, slow requests, and retained request capacity.
- `GET /api/v1/admin/rate-limits/status`: inspect the active rate-limit backend, configured limits, and current counter buckets with `key_prefix` and `limit` filters.
- `GET /api/v1/admin/rate-limits/health`: inspect rate-limit store health signals such as unsupported diagnostics, store errors, excessive bucket count, and stale hit pressure.
- `GET /api/v1/admin/e2ee/devices`: inspect E2EE device inventory with `user_id`, `active`, `page`, and `size` filters without returning key material.
- `GET /api/v1/admin/e2ee/devices/{device_id}`: inspect one E2EE device's redacted key inventory counts.
- `GET /api/v1/admin/e2ee/prekeys`: inspect one-time prekey inventory with `device_id`, `user_id`, `consumed`, `page`, and `size` filters without returning public keys.
- `GET /api/v1/admin/e2ee/health`: inspect E2EE inventory issues such as missing device owners, users without active devices, devices missing active signed prekeys, low available prekey counts, orphan prekeys, and duplicate active signed prekeys.
- `GET /api/v1/admin/database/status`: inspect database connection status, dialect, Alembic revision state, runtime schema completeness, and required table presence.
- `GET /api/v1/admin/database/tables`: inspect table row counts and required index presence.
- `GET /api/v1/admin/database/health`: inspect read-only database health checks and schema issues.
- `POST /api/v1/admin/database/backups`: create one server-local database backup.
- `GET /api/v1/admin/database/backups`: list database backup records.
- `POST /api/v1/admin/database/backups/prune`: preview or execute backup cleanup by retention criteria.
- `GET /api/v1/admin/database/backups/{backup_id}`: inspect one database backup record.
- `GET /api/v1/admin/database/backups/{backup_id}/download`: download one completed database backup as an attachment.
- `POST /api/v1/admin/database/backups/{backup_id}/verify`: verify one completed database backup without restoring it.
- `DELETE /api/v1/admin/database/backups/{backup_id}`: delete one server-local backup file and mark its record as deleted.
- `GET /api/v1/admin/users`: list users with `keyword`, `role`, `disabled`, `page`, and `size` filters.
- `GET /api/v1/admin/users/{user_id}`: inspect one user, including safe profile fields, device metadata, and business counts.
- `PATCH /api/v1/admin/users/{user_id}/role`: set a user role to `user` or `admin`.
- `POST /api/v1/admin/users/{user_id}/disable`: disable a user, invalidate existing tokens, and disconnect realtime sessions.
- `POST /api/v1/admin/users/{user_id}/enable`: re-enable a disabled user.
- `POST /api/v1/admin/users/{user_id}/force-logout`: invalidate existing tokens and disconnect realtime sessions.

User-management write operations are recorded in `admin_audit_logs`. Audit-log
responses redact sensitive detail keys such as passwords, tokens, credentials,
authorization headers, and secrets. The API does not expose password hashes,
tokens, private keys, or E2EE public key material in admin list/detail
responses. Database inspection APIs are read-only and redact database URL
passwords. Server logs are written to `LOG_DIR` (`data/logs` by default) with a
rotating `assistim.log` file. Admin log APIs read only that configured log
directory, reject path traversal, and redact sensitive values such as tokens,
passwords, secrets, credentials, and authorization headers before returning
query or download content. File storage inspection APIs scan only the configured
local upload directory, report relative `storage_key` values, and do not return
or audit local filesystem paths. Chat inspection APIs are read-only and expose
server-visible chat metadata and message content for administrator diagnostics;
they do not expose passwords, tokens, private keys, device keys, or E2EE key
material. Contact inspection APIs are read-only and expose friend-request and
friendship metadata needed to diagnose contact-list and private-chat visibility
issues. Group inspection APIs are read-only and expose group/session/member,
announcement, and avatar metadata needed to diagnose group-chat visibility and
profile drift. Moment inspection APIs are read-only and expose moment content,
author metadata, comments, likes, and interaction integrity checks needed to
diagnose timeline visibility and social interaction drift. Realtime and call
inspection APIs are read-only and expose in-memory WebSocket connection state
and active-call registry metadata needed to diagnose online presence and call
signaling drift; they do not force disconnect users or end calls. HTTP and
rate-limit inspection APIs are read-only and expose request method, path, status
code, duration, authenticated user id, rate-limit backend, configured limits,
and counter-bucket metadata needed to diagnose request failures and throttling;
they do not expose request headers, request bodies, authorization values,
tokens, passwords, or credentials. E2EE inspection APIs are read-only and expose
device/key inventory counts and state needed to diagnose verification and
decryption readiness; they do not return
identity keys, signing keys, signed prekey public keys, signatures, or one-time
prekey public keys. Database backup files are written to a
server-controlled local directory and are not exposed through public upload URLs.
Backup downloads are admin-only, require a completed backup record, and verify
the file remains inside the configured backup directory before streaming it.
Backup verification is admin-only, checks the same directory boundary, validates
recorded size and checksum, then runs SQLite `PRAGMA integrity_check` or
PostgreSQL `pg_restore --list` without restoring into the active database.
Backup deletion is also admin-only, verifies the same backup-directory boundary,
deletes only the server-local backup file, and keeps the database record with
`status=deleted` for auditability. SQLite backups use the SQLite backup API;
PostgreSQL backups require `pg_dump` on the server to create backups and
`pg_restore` to verify custom dump backups; both fail explicitly when
unavailable. Self-disable and self-demotion are blocked to avoid locking out the
only active administrator.

Backup cleanup accepts a JSON body with `keep_last`, `older_than_days`,
`include_failed`, `include_deleted`, and `dry_run`. At least one of `keep_last`
or `older_than_days` is required. `dry_run` defaults to `true`; execution mode
deletes only backup files inside the configured backup directory and marks
matched records as `deleted` without removing audit history.

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

