#!/usr/bin/env bash
set -euo pipefail

if (( $# == 0 )); then
  echo "用法：$0 owner/repo [owner/repo ...]" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  echo "缺少 gh CLI，无法读取 GitHub 基线状态" >&2
  exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "缺少 python3，无法执行审计" >&2
  exit 2
fi

if ! python3 -c 'import markdown_it, mdurl, yaml; assert int(yaml.__version__.split(".", 1)[0]) >= 6; assert markdown_it.__version__ == "3.0.0"; assert mdurl.__version__ == "0.1.2"' >/dev/null 2>&1; then
  echo "缺少固定审计依赖：PyYAML>=6、markdown-it-py==3.0.0、mdurl==0.1.2" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/audit_github_baseline.py" "$@"
