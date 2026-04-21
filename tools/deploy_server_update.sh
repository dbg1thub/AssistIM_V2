#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${1:-${REPO_ROOT}/deploy/docker/server.env}"
REMOTE_NAME="${ASSISTIM_GIT_REMOTE:-origin}"
CURRENT_BRANCH="$(git -C "${REPO_ROOT}" rev-parse --abbrev-ref HEAD)"

cd "${REPO_ROOT}"

echo "[assistim] updating repository"
echo "[assistim] remote: ${REMOTE_NAME}"
echo "[assistim] branch: ${CURRENT_BRANCH}"

git pull --ff-only "${REMOTE_NAME}" "${CURRENT_BRANCH}"

"${SCRIPT_DIR}/rebuild_api.sh" "${ENV_FILE}"

