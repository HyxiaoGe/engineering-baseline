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

check_agents_template() {
  if ! python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
template = (root / "templates" / "AGENTS.md").read_text()
contract = (root / "contracts" / "ci-cd-baseline.md").read_text()

for marker in (
    "PROJECT_REPLACE",
    "公共 MUST",
    "子目录 `AGENTS.md`",
    "独立 Git worktree",
    "Co-Authored-By: Codex <noreply@anthropic.com>",
):
    assert marker in template, marker

assert "AGENTS.md 覆盖边界" in contract
assert "不得降低" in contract
print("AGENTS 模板与覆盖契约通过")
PY
  then
    echo "FAIL: AGENTS 模板或覆盖契约不满足"
    failures=$((failures + 1))
  fi
}

check_baseline_ci_workflow() {
  if ! python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])
path = root / ".github" / "workflows" / "baseline-ci.yml"
document = yaml.load(path.read_text(), Loader=yaml.BaseLoader)

assert document["name"] == "Engineering baseline CI"
assert set(document["on"]) == {"pull_request", "push", "workflow_dispatch"}
assert document["on"]["pull_request"]["branches"] == ["master"]
assert document["on"]["push"]["branches"] == ["master"]
assert document["permissions"] == {"contents": "read"}
assert document["concurrency"]["cancel-in-progress"] == "true"

jobs = document["jobs"]
assert set(jobs) == {"baseline"}
job = jobs["baseline"]
assert job["name"] == "Baseline contract validation"
assert job["runs-on"] == "ubuntu-latest"
assert "environment" not in job

workflow_text = path.read_text()
assert "secrets." not in workflow_text
steps = job["steps"]
checkout = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
assert len(checkout) == 1
assert checkout[0]["uses"] == "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
assert checkout[0]["with"]["persist-credentials"] == "false"

commands = "\n".join(step.get("run", "") for step in steps)
for marker in (
    "PyYAML==6.0.3",
    "ruff==0.15.10",
    "shellcheck",
    "ruff check",
    "ruff format --check",
    "tests/test-audit.sh",
):
    assert marker in commands, marker

print("基线仓库 CI 工作流契约通过")
PY
  then
    echo "FAIL: 基线仓库 CI 工作流不满足最小权限与自测契约"
    failures=$((failures + 1))
  fi
}

check_central_audit_entrypoint() {
  if ! python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])
workflow_path = root / ".github" / "workflows" / "baseline-drift-audit.yml"
readme = (root / "README.md").read_text()
maintenance = (root / "MAINTENANCE.md").read_text()
registry = [
    line.strip()
    for line in (root / "repositories.txt").read_text().splitlines()
    if line.strip() and not line.lstrip().startswith("#")
]

assert not (root / ".github" / "actions" / "audit" / "action.yml").exists()
assert not (root / "templates" / "drift-audit.yml").exists()

workflow = yaml.load(workflow_path.read_text(), Loader=yaml.BaseLoader)
assert workflow["name"] == "Engineering baseline drift audit"
assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
assert workflow["on"]["schedule"] == [{"cron": "23 18 * * 0"}]
assert workflow["permissions"] == {"contents": "read"}
assert workflow["concurrency"]["cancel-in-progress"] == "false"

jobs = workflow["jobs"]
assert set(jobs) == {"audit"}
job = jobs["audit"]
assert job["runs-on"] == "ubuntu-latest"
assert job["environment"] == "audit"
assert job["timeout-minutes"] == "20"

steps = job["steps"]
checkout = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
assert len(checkout) == 1
assert checkout[0]["uses"] == "actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803"
assert checkout[0]["with"]["persist-credentials"] == "false"

tokens = [
    step
    for step in steps
    if step.get("uses", "").startswith("actions/create-github-app-token@")
]
assert len(tokens) == 1
token = tokens[0]
assert token["id"] == "app-token"
assert token["uses"] == "actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1"
assert token["with"]["client-id"] == "${{ vars.BASELINE_AUDIT_APP_CLIENT_ID }}"
assert "app-id" not in token["with"]
assert token["with"]["private-key"] == "${{ secrets.BASELINE_AUDIT_APP_PRIVATE_KEY }}"
assert token["with"]["owner"] == "HyxiaoGe"
assert {
    key: value
    for key, value in token["with"].items()
    if key.startswith("permission-")
} == {
    "permission-actions": "read",
    "permission-administration": "read",
    "permission-contents": "read",
    "permission-environments": "read",
    "permission-secrets": "read",
}
scoped_repositories = [
    f"HyxiaoGe/{name}"
    for name in token["with"]["repositories"].splitlines()
    if name.strip()
]
assert scoped_repositories == registry

commands = "\n".join(step.get("run", "") for step in steps)
assert "PyYAML==6.0.3" in commands
assert "scripts/audit-maintained-repositories.sh" in commands
audit_steps = [step for step in steps if "audit-maintained-repositories.sh" in step.get("run", "")]
assert len(audit_steps) == 1
assert audit_steps[0]["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token }}"

workflow_text = workflow_path.read_text()
assert "github.token" not in workflow_text
assert "secrets: inherit" not in workflow_text
for marker in (
    "GitHub App",
    "Administration: read",
    "Actions: read",
    "Contents: read",
    "Environments: read",
    "Secrets: read",
    "audit` Environment",
):
    assert marker in readme, marker
    assert marker in maintenance, marker

for forbidden in (
    "templates/drift-audit.yml",
    "PROJECT_REPLACE_BASELINE_SHA",
    "调用仓库自己的 `GITHUB_TOKEN`",
):
    assert forbidden not in readme, forbidden
    assert forbidden not in maintenance, forbidden

print("中央 GitHub App 漂移审计入口契约通过")
PY
  then
    echo "FAIL: 中央 GitHub App 漂移审计入口不满足最小权限契约"
    failures=$((failures + 1))
  fi
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
check_agents_template
check_baseline_ci_workflow
check_central_audit_entrypoint

if (( failures > 0 )); then
  echo "审计脚本 fixture 测试失败：${failures} 项"
  exit 1
fi

echo "审计脚本 fixture 测试通过"
