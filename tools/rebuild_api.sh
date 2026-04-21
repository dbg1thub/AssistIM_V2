#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/deploy/docker/server.env}"
COMPOSE_FILE="${REPO_ROOT}/deploy/docker/docker-compose.yml"
SERVICE_NAME="${ASSISTIM_API_SERVICE:-api}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "Missing compose file: ${COMPOSE_FILE}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

echo "[assistim] rebuilding service: ${SERVICE_NAME}"
echo "[assistim] repo root: ${REPO_ROOT}"
echo "[assistim] env file: ${ENV_FILE}"

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  up -d --build "${SERVICE_NAME}"

docker compose \
  --env-file "${ENV_FILE}" \
  -f "${COMPOSE_FILE}" \
  ps "${SERVICE_NAME}"

