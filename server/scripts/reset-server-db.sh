#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_ROOT="$(cd "${SERVER_ROOT}/.." && pwd)"
COMPOSE_FILE="${APP_ROOT}/deploy/docker/docker-compose.yml"
ENV_FILE=""
DATABASE_URL_OVERRIDE=""
PYTHON_BIN="${ASSISTIM_PYTHON:-}"
PSQL_BIN="${ASSISTIM_PSQL:-psql}"
CONFIRM_RESET="0"

usage() {
    cat <<'USAGE'
Usage: reset-server-db.sh --confirm-reset [options]

Options:
  --confirm-reset          Required. Drop and recreate the configured database.
  --env-file PATH          Env file to load. Defaults to server/.env, then deploy/docker/server.env.
  --database-url URL       Override DATABASE_URL from the env file.
  --compose-file PATH      Docker Compose file. Defaults to deploy/docker/docker-compose.yml.
  --python PATH            Python executable. Defaults to ASSISTIM_PYTHON, server/.venv/bin/python, python3, then python.
  --psql PATH              psql executable. Defaults to ASSISTIM_PSQL or psql.
  -h, --help               Show this help.
USAGE
}

trim() {
    local value="$1"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    printf '%s' "$value"
}

absolute_path() {
    local path="$1"
    local dir base
    dir="$(dirname "$path")"
    base="$(basename "$path")"
    printf '%s/%s' "$(cd "$dir" && pwd)" "$base"
}

select_default_env_file() {
    local candidate
    for candidate in "${SERVER_ROOT}/.env" "${APP_ROOT}/deploy/docker/server.env"; do
        if [[ -f "$candidate" ]]; then
            absolute_path "$candidate"
            return
        fi
    done
    printf '%s' "${SERVER_ROOT}/.env"
}

resolve_file_path() {
    local raw_path="$1"
    local candidate

    if [[ "$raw_path" = /* ]]; then
        printf '%s' "$raw_path"
        return
    fi

    for candidate in "${PWD}/${raw_path}" "${APP_ROOT}/${raw_path}" "${SERVER_ROOT}/${raw_path}"; do
        if [[ -f "$candidate" ]]; then
            absolute_path "$candidate"
            return
        fi
    done

    printf '%s' "${PWD}/${raw_path}"
}

load_env_file() {
    local file="$1"
    local line key value first last

    if [[ ! -f "$file" ]]; then
        echo "Env file not found: $file" >&2
        exit 1
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        line="$(trim "$line")"
        [[ -z "$line" || "${line:0:1}" == "#" || "$line" != *"="* ]] && continue

        key="$(trim "${line%%=*}")"
        value="$(trim "${line#*=}")"
        [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

        if [[ ${#value} -ge 2 ]]; then
            first="${value:0:1}"
            last="${value: -1}"
            if [[ ("$first" == '"' && "$last" == '"') || ("$first" == "'" && "$last" == "'") ]]; then
                value="${value:1:${#value}-2}"
            fi
        fi

        export "${key}=${value}"
    done < "$file"
}

resolve_python() {
    if [[ -n "$PYTHON_BIN" ]]; then
        if [[ ! -x "$PYTHON_BIN" ]]; then
            echo "Python executable is not runnable: $PYTHON_BIN" >&2
            exit 1
        fi
        printf '%s' "$PYTHON_BIN"
        return
    fi

    if [[ -x "${SERVER_ROOT}/.venv/bin/python" ]]; then
        printf '%s' "${SERVER_ROOT}/.venv/bin/python"
        return
    fi

    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return
    fi

    if command -v python >/dev/null 2>&1; then
        command -v python
        return
    fi

    echo "Python executable not found. Set ASSISTIM_PYTHON or pass --python." >&2
    exit 1
}

parse_database_url() {
    "$PYTHON_BIN" - "$DATABASE_URL" <<'PY'
from __future__ import annotations

import sys

from sqlalchemy.engine import make_url

raw_url = sys.argv[1].strip()
if not raw_url:
    raise SystemExit("DATABASE_URL is empty")

url = make_url(raw_url)
driver = url.drivername.lower()

if driver.startswith(("postgresql", "postgres")):
    database = url.database or ""
    if not database:
        raise SystemExit("PostgreSQL DATABASE_URL must include a database name")
    maintenance_url = url.set(drivername="postgresql", database="postgres")
    print("postgresql")
    print(database)
    print(url.host or "")
    print(str(url.port or 5432))
    print(maintenance_url.render_as_string(hide_password=False))
elif driver.startswith("sqlite"):
    database = url.database or ""
    if not database or database == ":memory:":
        raise SystemExit("SQLite DATABASE_URL must point to a file")
    print("sqlite")
    print(database)
    print("")
    print("")
    print("")
else:
    raise SystemExit(f"Unsupported DATABASE_URL driver: {url.drivername}")
PY
}

forbidden_postgres_database() {
    local database_name
    database_name="$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')"
    [[ "$database_name" == "postgres" || "$database_name" == "template0" || "$database_name" == "template1" ]]
}

reset_postgresql_database() {
    local target_db="$1"
    local maintenance_url="$2"

    if forbidden_postgres_database "$target_db"; then
        echo "Refusing to reset protected PostgreSQL database: $target_db" >&2
        exit 1
    fi

    if ! command -v "$PSQL_BIN" >/dev/null 2>&1 && [[ ! -x "$PSQL_BIN" ]]; then
        echo "psql executable not found: $PSQL_BIN" >&2
        exit 1
    fi

    "$PSQL_BIN" -v ON_ERROR_STOP=1 -v target_db="$target_db" "$maintenance_url" <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'target_db'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS :"target_db";
CREATE DATABASE :"target_db";
SQL
}

reset_sqlite_database() {
    local db_path="$1"
    local resolved_path

    if [[ "$db_path" = /* ]]; then
        resolved_path="$db_path"
    else
        resolved_path="${SERVER_ROOT}/${db_path}"
    fi

    mkdir -p "$(dirname "$resolved_path")"
    rm -f "$resolved_path" "${resolved_path}-wal" "${resolved_path}-shm"
}

has_docker_compose_database_config() {
    [[ -n "${POSTGRES_DB:-}" && -n "${POSTGRES_USER:-}" && -n "${POSTGRES_PASSWORD:-}" && -f "$COMPOSE_FILE" ]]
}

run_docker_compose_reset() {
    local -a dc
    if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
        dc=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
    else
        echo "docker compose is required for env files without DATABASE_URL." >&2
        exit 1
    fi

    echo "Target database:"
    echo "  type: postgresql (docker compose)"
    echo "  compose: ${COMPOSE_FILE}"
    echo "  env: ${ENV_FILE}"
    echo "  service: postgres"
    echo "  name: ${POSTGRES_DB}"

    "${dc[@]}" stop api
    "${dc[@]}" up -d postgres
    "${dc[@]}" exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 -v target_db="$POSTGRES_DB"' <<'SQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'target_db'
  AND pid <> pg_backend_pid();

DROP DATABASE IF EXISTS :"target_db";
CREATE DATABASE :"target_db";
SQL
    "${dc[@]}" run --rm api python -m alembic -c alembic.ini upgrade head
    "${dc[@]}" run --rm api python -m app.ops.seed_test_users
    "${dc[@]}" up -d api
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --confirm-reset)
            CONFIRM_RESET="1"
            shift
            ;;
        --env-file)
            ENV_FILE="$2"
            shift 2
            ;;
        --database-url)
            DATABASE_URL_OVERRIDE="$2"
            shift 2
            ;;
        --compose-file)
            COMPOSE_FILE="$2"
            shift 2
            ;;
        --python)
            PYTHON_BIN="$2"
            shift 2
            ;;
        --psql)
            PSQL_BIN="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$ENV_FILE" ]]; then
    ENV_FILE="$(select_default_env_file)"
else
    ENV_FILE="$(resolve_file_path "$ENV_FILE")"
fi

if [[ "$COMPOSE_FILE" != /* ]]; then
    COMPOSE_FILE="$(resolve_file_path "$COMPOSE_FILE")"
fi

load_env_file "$ENV_FILE"

if [[ -n "$DATABASE_URL_OVERRIDE" ]]; then
    export DATABASE_URL="$DATABASE_URL_OVERRIDE"
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
    if [[ "$CONFIRM_RESET" != "1" ]]; then
        echo "Refusing to reset without --confirm-reset." >&2
        exit 1
    fi
    if has_docker_compose_database_config; then
        run_docker_compose_reset
        echo "Database reset completed."
        exit 0
    fi
    echo "DATABASE_URL is not set and Docker Compose database settings were not found in: $ENV_FILE" >&2
    exit 1
fi

PYTHON_BIN="$(resolve_python)"
mapfile -t DB_INFO < <(parse_database_url)
DB_KIND="${DB_INFO[0]}"
DB_NAME="${DB_INFO[1]}"
DB_HOST="${DB_INFO[2]}"
DB_PORT="${DB_INFO[3]}"
DB_RESET_URL="${DB_INFO[4]}"

echo "Target database:"
echo "  type: ${DB_KIND}"
echo "  host: ${DB_HOST:-n/a}"
echo "  port: ${DB_PORT:-n/a}"
echo "  name: ${DB_NAME}"

if [[ "$CONFIRM_RESET" != "1" ]]; then
    echo "Refusing to reset without --confirm-reset." >&2
    exit 1
fi

case "$DB_KIND" in
    postgresql)
        reset_postgresql_database "$DB_NAME" "$DB_RESET_URL"
        ;;
    sqlite)
        reset_sqlite_database "$DB_NAME"
        ;;
    *)
        echo "Unsupported database type: $DB_KIND" >&2
        exit 1
        ;;
esac

cd "$SERVER_ROOT"
"$PYTHON_BIN" -m alembic upgrade head
"$PYTHON_BIN" -m app.ops.seed_test_users

echo "Database reset completed."
