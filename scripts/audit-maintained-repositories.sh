#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REGISTRY_FILE="${1:-${ROOT_DIR}/repositories.txt}"
AUDIT_SCRIPT="${SCRIPT_DIR}/audit-github-baseline.sh"

if [[ ! -f "${REGISTRY_FILE}" ]]; then
  echo "仓库清单不存在：${REGISTRY_FILE}" >&2
  exit 2
fi

repositories=()
while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  if [[ -n "${line}" ]]; then
    repositories+=("${line}")
  fi
done <"${REGISTRY_FILE}"

if (( ${#repositories[@]} == 0 )); then
  echo "仓库清单没有可审计条目：${REGISTRY_FILE}" >&2
  exit 2
fi

exec "${AUDIT_SCRIPT}" "${repositories[@]}"
