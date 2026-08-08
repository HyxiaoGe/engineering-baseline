#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-github-baseline.sh"
REGISTRY_AUDIT_SCRIPT="${ROOT_DIR}/scripts/audit-maintained-repositories.sh"
MOCK_BIN="${ROOT_DIR}/tests/bin"
FIXTURES_DIR="${ROOT_DIR}/tests/fixtures"
failures=0

run_expect_success() {
  local fixture_name="$1"
  local output

  if ! output="$(PATH="${MOCK_BIN}:${PATH}" AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/${fixture_name}" bash "${AUDIT_SCRIPT}" example/project 2>&1)"; then
    echo "FAIL: ${fixture_name} 应通过"
    echo "${output}"
    failures=$((failures + 1))
    return
  fi

  if ! grep -Fq "PASS example/project" <<<"${output}"; then
    echo "FAIL: ${fixture_name} 缺少通过摘要"
    echo "${output}"
    failures=$((failures + 1))
  fi
}

run_expect_failure() {
  local fixture_name="$1"
  local expected_code="$2"
  local output

  if output="$(PATH="${MOCK_BIN}:${PATH}" AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/${fixture_name}" bash "${AUDIT_SCRIPT}" example/project 2>&1)"; then
    echo "FAIL: ${fixture_name} 应失败"
    echo "${output}"
    failures=$((failures + 1))
    return
  fi

  if ! grep -Fq "${expected_code}" <<<"${output}"; then
    echo "FAIL: ${fixture_name} 未报告 ${expected_code}"
    echo "${output}"
    failures=$((failures + 1))
  fi
}

run_expect_failure_codes() {
  local fixture_name="$1"
  shift
  local output

  if output="$(PATH="${MOCK_BIN}:${PATH}" AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/${fixture_name}" bash "${AUDIT_SCRIPT}" example/project 2>&1)"; then
    echo "FAIL: ${fixture_name} 应失败"
    echo "${output}"
    failures=$((failures + 1))
    return
  fi

  local expected_code
  for expected_code in "$@"; do
    if ! grep -Fq "${expected_code}" <<<"${output}"; then
      echo "FAIL: ${fixture_name} 未报告 ${expected_code}"
      echo "${output}"
      failures=$((failures + 1))
    fi
  done
}

check_templates() {
  if ! python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])
known = {
    "actions/checkout": ("d23441a48e516b6c34aea4fa41551a30e30af803", "v6"),
    "actions/setup-node": ("249970729cb0ef3589644e2896645e5dc5ba9c38", "v6"),
    "docker/login-action": ("dbcb813823bdd20940b903addbd779551569679f", "v4.6.0"),
}
seen = set()
for path in sorted((root / "templates").glob("*.yml")):
    document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    for job in document.get("jobs", {}).values():
        for step in job.get("steps", []):
            target = step.get("uses")
            if not target:
                continue
            action, revision = target.rsplit("@", 1)
            if action in known:
                expected_revision, _ = known[action]
                assert revision == expected_revision, (path, action, revision)
                seen.add(action)
            if action == "actions/checkout":
                assert step.get("with", {}).get("persist-credentials") == "false", path
assert seen == set(known), seen
print("模板已知 Action 与 checkout 凭据契约通过")
PY
  then
    echo "FAIL: 模板已知 Action 或 checkout 凭据契约不满足"
    failures=$((failures + 1))
  fi
}

check_registry_entrypoint() {
  local temp_dir registry_file empty_registry output
  temp_dir="$(mktemp -d)"
  registry_file="${temp_dir}/repositories.txt"
  empty_registry="${temp_dir}/empty.txt"

  printf '%s\n' \
    '# 当前维护仓库' \
    '' \
    'example/project' \
    'example/another-project' >"${registry_file}"
  : >"${empty_registry}"

  if ! output="$(
    PATH="${MOCK_BIN}:${PATH}" \
      AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/good" \
      bash "${REGISTRY_AUDIT_SCRIPT}" "${registry_file}" 2>&1
  )"; then
    echo "FAIL: 仓库清单入口应审计全部有效条目"
    echo "${output}"
    failures=$((failures + 1))
  else
    for repo in example/project example/another-project; do
      if ! grep -Fq "PASS ${repo}" <<<"${output}"; then
        echo "FAIL: 仓库清单入口缺少 ${repo} 的通过摘要"
        echo "${output}"
        failures=$((failures + 1))
      fi
    done
  fi

  if output="$(bash "${REGISTRY_AUDIT_SCRIPT}" "${empty_registry}" 2>&1)"; then
    echo "FAIL: 空仓库清单应拒绝执行"
    echo "${output}"
    failures=$((failures + 1))
  elif ! grep -Fq "仓库清单没有可审计条目" <<<"${output}"; then
    echo "FAIL: 空仓库清单缺少稳定错误信息"
    echo "${output}"
    failures=$((failures + 1))
  fi

  rm -rf -- "${temp_dir}"
}

run_expect_success good
run_expect_failure mutable-action "[ACTION_PIN]"
run_expect_failure old-required-check "[REQUIRED_CHECK]"
run_expect_failure missing-dev-environment "[DEV_ENVIRONMENT]"
run_expect_failure pr-secret "[PR_SECRET]"
run_expect_failure pr-self-hosted "[PR_RUNNER]"
run_expect_failure pr-deploy-permission "[PR_PERMISSION]"
run_expect_failure manual-non-master "[RELEASE_EVENT]"
run_expect_failure wrong-known-action-sha "[ACTION_PIN]"
run_expect_failure protection-contexts-only "[REQUIRED_CHECK_APP]"
run_expect_failure protection-missing-app "[REQUIRED_CHECK_APP]"
run_expect_failure protection-wrong-app "[REQUIRED_CHECK_APP]"
run_expect_failure flow-uses-mutable "[ACTION_PIN]"
run_expect_failure flow-job-write "[PR_PERMISSION]"
run_expect_failure pr-extra-event "[PR_EVENT]"
run_expect_failure pr-branches-ignore-master "[PR_EVENT]"
run_expect_failure pr-extra-branch "[PR_EVENT]"
run_expect_failure pr-top-env-secret "[PR_SECRET]"
run_expect_failure pr-buildx-push "[PR_DEPLOY]"
run_expect_failure pr-docker-image-push "[PR_DEPLOY]"
run_expect_failure pr-helm "[PR_DEPLOY]"
run_expect_failure pr-rsync "[PR_DEPLOY]"
run_expect_failure fake-check-name "[PR_CHECK_NAME]"
run_expect_failure fake-smoke "[DEPLOY_SMOKE]"
run_expect_failure local-action-indirect-deploy "[PR_DEPLOY]"
run_expect_failure local-action-indirect-secret "[PR_SECRET]"
run_expect_failure local-action-indirect-mutable "[ACTION_PIN]"
run_expect_failure local-action-path-escape "[LOCAL_ACTION]"
run_expect_failure local-action-missing "[LOCAL_ACTION]"
run_expect_failure local-action-symlink "[LOCAL_ACTION]"
run_expect_failure root-local-action "[ACTION_PIN]"
run_expect_failure checkout-persist-missing "[CHECKOUT_CREDENTIAL]"
run_expect_failure checkout-persist-env-fake "[CHECKOUT_CREDENTIAL]"
run_expect_failure default-branch-main "[DEFAULT_BRANCH]"
run_expect_failure unknown-workflow-structure "[WORKFLOW_STRUCTURE]"
run_expect_success auxiliary-codeql
run_expect_failure_codes auxiliary-unsafe "[AUX_PR_SECRET]" "[AUX_PR_ENVIRONMENT]" "[AUX_PR_RUNNER]" "[AUX_PR_DEPLOY]"
run_expect_failure_codes pagination "[AUX_PR_DEPLOY]" "[REPO_SECRET_BOUNDARY]" "STALE_REPOSITORY_SECRET"
run_expect_failure manual-publish-unguarded-login "[RELEASE_EVENT]"
run_expect_failure manual-guard-or-true "[RELEASE_EVENT]"
run_expect_failure manual-dependent-custom-if "[RELEASE_EVENT]"
run_expect_failure smoke-no-compare "[DEPLOY_SMOKE]"
run_expect_success smoke-if-exec
run_expect_failure release-dynamic-secret "[SECRET_ENV_BOUNDARY]"
run_expect_failure release-secrets-inherit "[SECRET_ENV_BOUNDARY]"
run_expect_success dynamic-platform-workflow
run_expect_failure stale-active-workflow "[WORKFLOW_LIST]"
run_expect_failure auxiliary-missing-permissions "[AUX_PR_PERMISSION]"
check_templates
check_registry_entrypoint

if (( failures > 0 )); then
  echo "审计脚本 fixture 测试失败：${failures} 项"
  exit 1
fi

echo "审计脚本 fixture 测试通过"
