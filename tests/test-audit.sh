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

run_expect_unavailable() {
  local fixture_name="$1"
  local output
  local status=0

  output="$(PATH="${MOCK_BIN}:${PATH}" AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/${fixture_name}" bash "${AUDIT_SCRIPT}" example/project 2>&1)" || status=$?

  if (( status != 3 )); then
    echo "FAIL: ${fixture_name} 应以退出码 3 报告审计未完成，实际 ${status}"
    echo "${output}"
    failures=$((failures + 1))
    return
  fi

  local marker
  for marker in "ERROR example/project" "[API_UNAVAILABLE]" "未能完成审计"; do
    if ! grep -Fq "${marker}" <<<"${output}"; then
      echo "FAIL: ${fixture_name} 缺少 ${marker}"
      echo "${output}"
      failures=$((failures + 1))
    fi
  done
}

run_expect_success_on_branch() {
  local fixture_name="$1"
  local branch="$2"
  local output

  if ! output="$(
    PATH="${MOCK_BIN}:${PATH}" \
      AUDIT_FIXTURE_DIR="${FIXTURES_DIR}/${fixture_name}" \
      BASELINE_DEFAULT_BRANCH="${branch}" \
      bash "${AUDIT_SCRIPT}" example/project 2>&1
  )"; then
    echo "FAIL: ${fixture_name} 在 ${branch} 分支下应通过"
    echo "${output}"
    failures=$((failures + 1))
    return
  fi

  if ! grep -Fq "受保护分支 ${branch}" <<<"${output}"; then
    echo "FAIL: ${fixture_name} 未回显受保护分支 ${branch}"
    echo "${output}"
    failures=$((failures + 1))
  fi
}

check_expression_unit_tests() {
  if ! output="$(cd "${ROOT_DIR}" && python3 -m unittest discover -s tests/unit -t "${ROOT_DIR}" -v 2>&1)"; then
    echo "FAIL: 表达式解析器单元测试不通过"
    echo "${output}"
    failures=$((failures + 1))
  fi
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
for path in (root / "templates" / "pr-ci.yml", root / "templates" / "release.yml"):
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
root_agents = (root / "AGENTS.md").read_text()
contract = (root / "contracts" / "ci-cd-baseline.md").read_text()
review_contract = (root / "contracts" / "codex-code-review.md").read_text()
readme = (root / "README.md").read_text()
maintenance = (root / "MAINTENANCE.md").read_text()
error_codes = (root / "contracts" / "error-codes.md").read_text()
audit_entrypoint = (root / "scripts" / "audit-github-baseline.sh").read_text()
audit_source = (root / "scripts" / "audit_github_baseline.py").read_text()

def section_content(document, heading):
    lines = document.splitlines()
    start = lines.index(heading) + 1
    section = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line.rstrip())
    return "\n".join(section).strip()


def section_bullets(document, heading):
    return [
        line
        for line in section_content(document, heading).splitlines()
        if line.startswith("- ")
    ]

# 这里只断言结构性不变量。公共 MUST 的措辞由 contracts/ 单独承载，
# 不再用中文短语把 README/MAINTENANCE 的散文钉死——那样只能证明某个词出现过。
assert "PROJECT_REPLACE" in template, "模板必须保留待替换占位符"

# 根规则与模板都必须提供官方 Reviewer 能直接消费的规则块。
for name, document in (("templates/AGENTS.md", template), ("AGENTS.md", root_agents)):
    assert "## Code Review Rules" in document, name
    bullets = section_bullets(document, "## Code Review Rules")
    # 官方建议保持两到三条简洁约束。
    assert 2 <= len(bullets) <= 3, (name, len(bullets))
    review_rules = section_content(document, "## Code Review Rules")
    assert "正例：" in review_rules and "反例：" in review_rules, name

# 契约文件必须存在且保留其顶层章节骨架。
for name, document, headings in (
    (
        "contracts/ci-cd-baseline.md",
        contract,
        ("## 8. 规则漂移", "## 9. AGENTS.md 覆盖边界"),
    ),
    (
        "contracts/codex-code-review.md",
        review_contract,
        ("## 4. Finding 处置与收敛", "## 5. v1 合并边界", "## 6. 审计与验收"),
    ),
):
    for heading in headings:
        assert heading in document, (name, heading)

# README 与 MAINTENANCE 是入口，必须指回契约而不是复述契约。
for name, document in (("README.md", readme), ("MAINTENANCE.md", maintenance)):
    assert "contracts/ci-cd-baseline.md" in document, name
    assert "contracts/codex-code-review.md" in document, name
    assert "contracts/error-codes.md" in document, name

# 固定 CommonMark parser 是 [CODE_REVIEW_RULES] 的判定基础，不得回退成手写状态机。
for marker in ("markdown-it-py==3.0.0", "mdurl==0.1.2"):
    assert marker in audit_entrypoint, marker
assert 'MarkdownIt("commonmark")' in audit_source
for forbidden in ("markdown_fence", "raw_html_block_start"):
    assert forbidden not in audit_source, forbidden
# 分支自动删除按项目分支模型配置，不作为公共审计门禁。
assert "delete_branch_on_merge" not in audit_source

# 错误码是公开接口：实现与参考文档必须双向完全一致。
import re

emitted = set(re.findall(r"\[([A-Z][A-Z0-9_]+)\]", audit_source))
documented = set(re.findall(r"`\[([A-Z][A-Z0-9_]+)\]`", error_codes))
assert emitted == documented, {
    "实现有但文档缺": sorted(emitted - documented),
    "文档有但实现缺": sorted(documented - emitted),
}

# 结论行与退出码同样是接口。
for token in ("PASS owner/repo", "FAIL owner/repo", "ERROR owner/repo"):
    assert token in error_codes, token
for token in ("`0`", "`1`", "`2`", "`3`"):
    assert token in error_codes, token
for token in ('print(f"PASS', 'print(f"FAIL', 'print(f"ERROR'):
    assert token in audit_source, token

print("AGENTS 模板、契约骨架与错误码参考通过")
PY
  then
    echo "FAIL: AGENTS 模板、契约骨架或错误码参考不满足"
    failures=$((failures + 1))
  fi
}

check_release_safety_contract() {
  if ! python3 - "${ROOT_DIR}" <<'PY'
from pathlib import Path
import sys

import yaml

root = Path(sys.argv[1])
template_path = root / "templates" / "release.yml"
workflow = yaml.load(template_path.read_text(), Loader=yaml.BaseLoader)
manifest = yaml.load(
    (root / "templates" / "release-safety.yml").read_text(),
    Loader=yaml.BaseLoader,
)
pr_workflow = yaml.load(
    (root / "templates" / "pr-ci.yml").read_text(),
    Loader=yaml.BaseLoader,
)
dispatch = workflow["on"]["workflow_dispatch"]
assert set(dispatch["inputs"]) == {"rollback_sha", "rollback_reason"}
assert workflow["concurrency"] == {
    "group": "master-release",
    "cancel-in-progress": "false",
}
assert set(workflow["jobs"]) == {
    "validate_release",
    "publish",
    "deploy",
    "finalize",
}
assert manifest["workflow"] == ".github/workflows/release.yml"
assert manifest["jobs"] == {
    "prepare": "validate_release",
    "publish": "publish",
    "deploy": "deploy",
    "finalize": "finalize",
}
assert manifest["steps"]["verify"] == ["verify_candidate"]
assert manifest["steps"]["migrations"] == ["migrate"]
assert manifest["contract_test"]["pr_step"] == "release_safety_contract"
pr_steps = pr_workflow["jobs"]["validation"]["steps"]
contract_steps = [
    step for step in pr_steps if step.get("id") == "release_safety_contract"
]
assert len(contract_steps) == 1
assert "if" not in contract_steps[0]
assert contract_steps[0].get("continue-on-error") not in ("true", True)
assert contract_steps[0]["run"] == manifest["contract_test"]["path"]
contract_entry = root / "templates" / "release-safety-contract.sh"
assert contract_entry.stat().st_mode & 0o111 == 0o111
assert contract_entry.read_text().startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
deploy = workflow["jobs"]["deploy"]
step_ids = [step.get("id") for step in deploy["steps"] if step.get("id")]
assert step_ids == [
    "capture_previous",
    "migrate",
    "candidate_deploy",
    "verify_candidate",
    "rollback_previous",
    "cleanup_images",
    "preserve_failure",
]
assert deploy["steps"][1]["id"] == "capture_previous"
assert deploy["steps"][-2]["if"] == "${{ success() }}"
template_text = template_path.read_text()
for marker in (
    "DEPLOY_TARGET_SHA",
    'expected_prefix="${IMAGE_NAME}:"',
    '[[ "${previous_sha}" =~ ^[0-9a-f]{40}$ ]]',
    '[[ "${previous_image_id}" =~ ^sha256:[0-9a-f]{64}$ ]]',
    'previous_sha="${PREVIOUS_IMAGE_REF#"${expected_prefix}"}"',
    '[[ "${previous_sha}" =~ ^[0-9a-f]{40}$ ]]',
    '[[ "${PREVIOUS_IMAGE_ID}" =~ ^sha256:[0-9a-f]{64}$ ]]',
    'ci-container-smoke.sh "${previous_sha}"',
    "id: finalize_release",
    "id: finalize_failure",
):
    assert marker in template_text, marker
assert 'ci-container-smoke.sh "${PREVIOUS_IMAGE_ID}"' not in template_text

# 发布安全的公共 MUST 只以契约为事实源；README/MAINTENANCE 作为入口另行校验链接。
contract_path = root / "contracts" / "ci-cd-baseline.md"
contract_text = contract_path.read_text()
for marker in (
    "expand/contract",
    "禁止自动执行 `alembic downgrade`",
    "首次部署",
    "DEPLOY_TARGET_SHA",
    "rollback_sha",
    ".github/release-safety.yml",
):
    assert marker in contract_text, marker
assert "中央审计" in contract_text
assert (
    "不解释任意 shell" in contract_text or "不声称从原始 shell" in contract_text
)

print("发布安全模板与维护合同通过")
PY
  then
    echo "FAIL: 发布安全模板或维护合同不满足 v1 契约"
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
    "markdown-it-py==3.0.0",
    "mdurl==0.1.2",
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
assert set(jobs) == {"audit", "notify"}
job = jobs["audit"]
assert job["runs-on"] == "ubuntu-latest"
assert job["environment"] == "audit"
assert job["timeout-minutes"] == "20"
assert "permissions" not in job, "审计 job 沿用顶层 contents:read"

# 通知与审计必须凭据隔离：审计 job 不碰仓库自身 token，notify job 不碰 App token。
notify = jobs["notify"]
assert notify["needs"] == "audit"
assert notify["if"].startswith("failure()")
assert "schedule" in notify["if"], "只对无人值守的计划任务开 issue"
assert notify["permissions"] == {"contents": "read", "issues": "write"}
assert "environment" not in notify, "notify 不得进入 audit Environment"
notify_text = yaml.dump(notify)
assert "app-token" not in notify_text, "notify 不得使用只读审计 App 的令牌"
assert "BASELINE_AUDIT_APP_PRIVATE_KEY" not in notify_text

steps = job["steps"]
audit_job_text = yaml.dump(job)
for forbidden in ("secrets.GITHUB_TOKEN", "github.token", "issues:"):
    assert forbidden not in audit_job_text, forbidden
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
assert "markdown-it-py==3.0.0" in commands
assert "mdurl==0.1.2" in commands
assert "scripts/audit-maintained-repositories.sh" in commands
audit_steps = [step for step in steps if "audit-maintained-repositories.sh" in step.get("run", "")]
assert len(audit_steps) == 1
assert audit_steps[0]["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token }}"
# 退出码必须原样传出，notify 才能区分漂移与审计未完成。
assert audit_steps[0]["id"] == "audit"
assert 'exit "${status}"' in audit_steps[0]["run"]
assert job["outputs"]["status"] == "${{ steps.audit.outputs.status }}"

workflow_text = workflow_path.read_text()
assert "secrets: inherit" not in workflow_text

# App 权限是双向不变量：workflow 实际申请的每一项都必须在维护手册里有据可查。
requested = {
    key.removeprefix("permission-").capitalize()
    for key in token["with"]
    if key.startswith("permission-")
}
for name in requested:
    assert f"{name}: read" in maintenance, name
# Metadata 由 GitHub 强制携带，不出现在 with 里，但同样必须被记录。
assert "Metadata: read" in maintenance
assert "Engineering Baseline Auditor" in maintenance
assert "audit` Environment" in maintenance

for forbidden in (
    "templates/drift-audit.yml",
    "PROJECT_REPLACE_BASELINE_SHA",
):
    assert forbidden not in readme, forbidden
    assert forbidden not in maintenance, forbidden

assert "公开仓库维护" in readme
assert "私有仓库维护" not in readme

print("中央 GitHub App 漂移审计入口契约通过")
PY
  then
    echo "FAIL: 中央 GitHub App 漂移审计入口不满足最小权限契约"
    failures=$((failures + 1))
  fi
}

run_expect_success good
run_expect_failure repository-auto-merge-enabled "[REPOSITORY_MERGE_POLICY]"
# 字段缺失是"看不到"而非"开着"：必须报审计未完成，不能伪装成漂移。
run_expect_unavailable repository-auto-merge-unknown
run_expect_failure code-review-rules-missing "[CODE_REVIEW_RULES]"
run_expect_failure code-review-rules-symlink "[CODE_REVIEW_RULES]"
run_expect_failure code-review-rules-heading-missing "[CODE_REVIEW_RULES]"
run_expect_failure code-review-rules-heading-in-fence "[CODE_REVIEW_RULES]"
run_expect_failure code-review-rules-heading-in-html-comment "[CODE_REVIEW_RULES]"
run_expect_failure code-review-rules-heading-in-raw-html "[CODE_REVIEW_RULES]"
run_expect_success code-review-rules-heading-after-fences
run_expect_success code-review-rules-heading-after-inline-code
run_expect_success code-review-rules-heading-after-autolink
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
run_expect_success_on_branch main-default-branch main
run_expect_unavailable api-unavailable
run_expect_failure unknown-workflow-structure "[WORKFLOW_STRUCTURE]"
run_expect_success auxiliary-codeql
run_expect_failure_codes auxiliary-unsafe "[AUX_PR_SECRET]" "[AUX_PR_ENVIRONMENT]" "[AUX_PR_RUNNER]" "[AUX_PR_DEPLOY]"
run_expect_failure_codes pagination "[AUX_PR_DEPLOY]" "[REPO_SECRET_BOUNDARY]" "STALE_REPOSITORY_SECRET"
run_expect_failure manual-publish-unguarded-login "[ROLLBACK_GUARD]"
run_expect_failure manual-guard-or-true "[RELEASE_EVENT]"
run_expect_failure manual-dependent-custom-if "[ROLLBACK_GUARD]"
run_expect_failure rollback-capture-after-migration "[ROLLBACK_CAPTURE]"
run_expect_failure rollback-always-guard "[ROLLBACK_GUARD]"
run_expect_failure rollback-publish-still-runs "[ROLLBACK_GUARD]"
run_expect_failure rollback-cleanup-always "[RELEASE_FAILURE_STATE]"
run_expect_failure release-concurrency-cancel "[RELEASE_CONCURRENCY]"
run_expect_failure rollback-continue-on-error "[RELEASE_FAILURE_STATE]"
run_expect_failure failure-continue-on-error "[RELEASE_FAILURE_STATE]"
run_expect_failure finalize-failure-continue-on-error "[RELEASE_FAILURE_STATE]"
run_expect_failure rollback-migration-still-runs "[ROLLBACK_GUARD]"
run_expect_failure rollback-no-failure-preserve "[RELEASE_FAILURE_STATE]"
run_expect_failure manual-deploy-bypass "[RELEASE_WORKFLOW]"
run_expect_failure rollback-cleanup-before-rollback "[ROLLBACK_CAPTURE]"
run_expect_failure rollback-before-candidate "[ROLLBACK_CAPTURE]"
run_expect_success profile-fusion-api
run_expect_success profile-fusion-ui
run_expect_success profile-audio-api
run_expect_success profile-audio-ui
run_expect_failure manifest-missing-reference "[RELEASE_MANIFEST]"
run_expect_failure manifest-duplicate-role "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-conditional "[RELEASE_MANIFEST]"
run_expect_failure contract-job-conditional "[RELEASE_MANIFEST]"
run_expect_failure contract-job-continue-on-error "[RELEASE_MANIFEST]"
run_expect_failure contract-job-needs "[RELEASE_MANIFEST]"
run_expect_failure contract-check-name-duplicate "[RELEASE_MANIFEST]"
run_expect_failure contract-file-missing "[RELEASE_MANIFEST]"
run_expect_failure contract-file-not-executable "[RELEASE_MANIFEST]"
run_expect_failure contract-continue-on-error "[RELEASE_MANIFEST]"
run_expect_failure contract-step-continue-on-error-false "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-echo "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-checkout "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-test-file "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-prefixed-true "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-or-true "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-semicolon "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-pipe "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-custom-shell "[RELEASE_MANIFEST]"
run_expect_failure contract-gate-working-directory "[RELEASE_MANIFEST]"
run_expect_failure contract-job-default-shell "[RELEASE_MANIFEST]"
run_expect_failure contract-workflow-default-shell "[RELEASE_MANIFEST]"
run_expect_failure contract-job-default-working-directory "[RELEASE_MANIFEST]"
run_expect_failure contract-workflow-default-working-directory "[RELEASE_MANIFEST]"
run_expect_failure semantic-publish-no-master "[ROLLBACK_GUARD]"
run_expect_failure semantic-publish-no-rollback "[ROLLBACK_GUARD]"
run_expect_failure semantic-publish-or-true "[ROLLBACK_GUARD]"
run_expect_failure semantic-publish-string-decoy "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-no-master "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-implicit-rollback "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-string-decoy "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-normal-dead "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-rollback-dead "[ROLLBACK_GUARD]"
run_expect_failure semantic-deploy-prepare-result-missing "[ROLLBACK_GUARD]"
run_expect_failure semantic-migration-no-rollback "[ROLLBACK_GUARD]"
run_expect_failure semantic-migration-or-true "[ROLLBACK_GUARD]"
run_expect_failure semantic-migration-string-decoy "[ROLLBACK_GUARD]"
run_expect_failure semantic-signal-inconsistent "[ROLLBACK_GUARD]"
run_expect_failure semantic-rollback-or "[ROLLBACK_GUARD]"
run_expect_failure semantic-rollback-extra-false "[ROLLBACK_GUARD]"
run_expect_failure semantic-rollback-extra-success "[ROLLBACK_GUARD]"
run_expect_failure semantic-finalize-no-master "[RELEASE_FAILURE_STATE]"
run_expect_failure semantic-finalize-extra-false "[RELEASE_FAILURE_STATE]"
run_expect_failure release-local-action-mutable "[ACTION_PIN]"
run_expect_failure release-local-action-missing "[LOCAL_ACTION]"
run_expect_failure release-prepare-local-action-deploy "[RELEASE_EVENT]"
run_expect_failure release-undeclared-self-hosted "[RELEASE_MANIFEST]"
run_expect_failure release-job-write-permission "[RELEASE_PERMISSION]"
run_expect_failure release-publish-job-continue-on-error "[RELEASE_FAILURE_STATE]"
run_expect_failure release-deploy-job-continue-on-error "[RELEASE_FAILURE_STATE]"
run_expect_success release-job-continue-on-error-false
run_expect_failure release-concurrency-dynamic "[RELEASE_CONCURRENCY]"
run_expect_failure release-concurrency-job-dynamic "[RELEASE_CONCURRENCY]"
run_expect_success release-concurrency-format
run_expect_failure release-concurrency-format-dynamic "[RELEASE_CONCURRENCY]"
run_expect_failure docker-action-mutable "[ACTION_PIN]"
run_expect_success docker-action-digest
# 中央审计有意不解释多行 shell 控制流；项目可执行契约测试负责拒绝此类伪造。
run_expect_success shell-opaque-control-flow
run_expect_success smoke-if-exec
run_expect_failure release-dynamic-secret "[SECRET_ENV_BOUNDARY]"
run_expect_failure release-secrets-inherit "[SECRET_ENV_BOUNDARY]"
run_expect_success dynamic-platform-workflow
run_expect_failure stale-active-workflow "[WORKFLOW_LIST]"
# 未知的 dynamic/ workflow 仍然 fail-closed，但必须回显 name 与 path 供定位。
run_expect_failure_codes dynamic-unknown-workflow \
  "[WORKFLOW_LIST]" \
  "'CodeQL'" \
  "'dynamic/github-code-scanning/codeql'"
run_expect_failure auxiliary-missing-permissions "[AUX_PR_PERMISSION]"
check_expression_unit_tests
check_templates
check_registry_entrypoint
check_agents_template
check_release_safety_contract
check_baseline_ci_workflow
check_central_audit_entrypoint

if (( failures > 0 )); then
  echo "审计脚本 fixture 测试失败：${failures} 项"
  exit 1
fi

echo "审计脚本 fixture 测试通过"
