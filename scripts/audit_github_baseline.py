#!/usr/bin/env python3
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import json
from pathlib import PurePosixPath
import re
import subprocess
import sys
from typing import Any, Iterable
from urllib.parse import quote

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SECRET_PATTERN = re.compile(
    r"\bsecrets(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\])"
)
SECRET_CONTEXT_PATTERN = re.compile(r"\bsecrets(?:\.|\[|\b)")
ALLOWED_IMPLICIT_SECRETS = {"GITHUB_TOKEN"}
KNOWN_ACTIONS = {
    "actions/checkout": ("d23441a48e516b6c34aea4fa41551a30e30af803", "v6"),
    "actions/create-github-app-token": (
        "bcd2ba49218906704ab6c1aa796996da409d3eb1",
        "v3",
    ),
    "actions/setup-node": ("249970729cb0ef3589644e2896645e5dc5ba9c38", "v6"),
    "docker/login-action": ("dbcb813823bdd20940b903addbd779551569679f", "v4.6.0"),
}
ALLOWED_AUX_PERMISSIONS = {"contents": "read", "security-events": "write"}


class AuditError(RuntimeError):
    pass


@dataclass
class UseReference:
    target: str
    line: int
    parent: dict[str, Any]


@dataclass
class ParsedYaml:
    path: str
    text: str
    data: dict[str, Any]
    uses: list[UseReference]
    kind: str


@dataclass
class RepositorySource:
    repo: str
    workflows: dict[str, ParsedYaml]
    tree: dict[str, dict[str, Any]]
    local_actions: dict[str, ParsedYaml] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def gh_api(repo: str, suffix: str, *, optional: bool = False) -> Any | None:
    endpoint = f"repos/{repo}" if not suffix else f"repos/{repo}/{suffix}"
    result = subprocess.run(
        ["gh", "api", endpoint],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        if optional:
            return None
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"退出码 {result.returncode}"
        raise AuditError(f"GET {endpoint} 失败：{message}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AuditError(f"GET {endpoint} 返回了无效 JSON") from error


def gh_api_paginated(repo: str, suffix: str, list_key: str) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    page = 1
    total: int | None = None
    while total is None or len(collected) < total:
        separator = "&" if "?" in suffix else "?"
        payload = gh_api(repo, f"{suffix}{separator}per_page=100&page={page}")
        if not isinstance(payload, dict):
            raise AuditError(f"{suffix} 分页响应不是对象")
        if total is None:
            raw_total = payload.get("total_count")
            if not isinstance(raw_total, int) or raw_total < 0:
                raise AuditError(f"{suffix} 缺少合法 total_count")
            total = raw_total
        items = payload.get(list_key)
        if not isinstance(items, list) or any(
            not isinstance(item, dict) for item in items
        ):
            raise AuditError(f"{suffix} 的 {list_key} 不是对象数组")
        if not items and len(collected) < total:
            raise AuditError(f"{suffix} 第 {page} 页提前为空，拒绝不完整审计")
        collected.extend(items)
        page += 1
    if len(collected) != total:
        raise AuditError(f"{suffix} total_count 与分页结果数量不一致")
    return collected


def repository_content(repo: str, path: str) -> str:
    payload = gh_api(repo, f"contents/{quote(path, safe='/')}?ref=master")
    if not isinstance(payload, dict) or payload.get("encoding") != "base64":
        raise AuditError(f"无法解码 {path}：Contents API 未返回 base64 内容")
    try:
        raw = base64.b64decode(payload["content"], validate=False)
        return raw.decode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as error:
        raise AuditError(f"无法解码 {path}") from error


def convert_node(node: Node, mapping_lines: dict[int, dict[str, int]]) -> Any:
    if isinstance(node, ScalarNode):
        return node.value
    if isinstance(node, SequenceNode):
        return [convert_node(child, mapping_lines) for child in node.value]
    if isinstance(node, MappingNode):
        result: dict[str, Any] = {}
        key_lines: dict[str, int] = {}
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                raise AuditError("YAML mapping key 必须是标量")
            key = key_node.value
            if key in result:
                raise AuditError(f"YAML 含重复 key：{key}")
            result[key] = convert_node(value_node, mapping_lines)
            key_lines[key] = value_node.start_mark.line
        mapping_lines[id(result)] = key_lines
        return result
    raise AuditError(f"不支持的 YAML node：{type(node).__name__}")


def walk_mappings(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_mappings(child)


def parse_yaml(path: str, text: str, kind: str) -> ParsedYaml:
    try:
        node = yaml.compose(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        raise AuditError(f"{path} YAML 无法解析：{error}") from error
    if node is None:
        raise AuditError(f"{path} YAML 为空")
    mapping_lines: dict[int, dict[str, int]] = {}
    data = convert_node(node, mapping_lines)
    if not isinstance(data, dict):
        raise AuditError(f"{path} 顶层必须是 mapping")
    uses: list[UseReference] = []
    for mapping in walk_mappings(data):
        target = mapping.get("uses")
        if target is None:
            continue
        if not isinstance(target, str):
            raise AuditError(f"{path} uses 必须是字符串")
        uses.append(
            UseReference(
                target=target,
                line=mapping_lines[id(mapping)]["uses"],
                parent=mapping,
            )
        )
    parsed = ParsedYaml(path=path, text=text, data=data, uses=uses, kind=kind)
    validate_document_structure(parsed)
    return parsed


def validate_document_structure(document: ParsedYaml) -> None:
    data = document.data
    if document.kind == "workflow":
        on = data.get("on")
        permissions = data.get("permissions")
        jobs = data.get("jobs")
        if not isinstance(on, dict):
            raise AuditError(f"{document.path} on 必须是 mapping")
        if permissions is not None and not isinstance(permissions, dict):
            raise AuditError(f"{document.path} permissions 必须是 mapping")
        if not isinstance(jobs, dict) or not jobs:
            raise AuditError(f"{document.path} jobs 必须是非空 mapping")
        for job_id, job in jobs.items():
            if not isinstance(job_id, str) or not isinstance(job, dict):
                raise AuditError(f"{document.path} job 必须是 mapping")
            for key in ("permissions", "environment"):
                if (
                    key == "permissions"
                    and key in job
                    and not isinstance(job[key], dict)
                ):
                    raise AuditError(
                        f"{document.path} job {job_id} permissions 必须是 mapping"
                    )
                if (
                    key == "environment"
                    and key in job
                    and not isinstance(job[key], (str, dict))
                ):
                    raise AuditError(
                        f"{document.path} job {job_id} environment 结构无效"
                    )
            steps = job.get("steps")
            if steps is not None:
                if not isinstance(steps, list) or any(
                    not isinstance(step, dict) for step in steps
                ):
                    raise AuditError(
                        f"{document.path} job {job_id} steps 必须是 mapping 数组"
                    )
    elif document.kind == "action":
        runs = data.get("runs")
        if not isinstance(runs, dict):
            raise AuditError(f"{document.path} local Action runs 必须是 mapping")
        steps = runs.get("steps")
        if runs.get("using") == "composite" and (
            not isinstance(steps, list)
            or any(not isinstance(step, dict) for step in steps)
        ):
            raise AuditError(f"{document.path} composite steps 必须是 mapping 数组")


def event_map(document: ParsedYaml) -> dict[str, Any]:
    on = document.data["on"]
    assert isinstance(on, dict)
    return on


def jobs_map(document: ParsedYaml) -> dict[str, dict[str, Any]]:
    jobs = document.data["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def environment_name(job: dict[str, Any]) -> str | None:
    environment = job.get("environment")
    if isinstance(environment, str):
        return environment
    if isinstance(environment, dict):
        name = environment.get("name")
        return name if isinstance(name, str) else None
    return None


def deployment_false(job: dict[str, Any]) -> bool:
    environment = job.get("environment")
    return isinstance(environment, dict) and environment.get("deployment") == "false"


def scalar_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_strings(child)


def referenced_secret_names(value: Any) -> set[str]:
    names: set[str] = set()
    for text in scalar_strings(value):
        for dot_name, bracket_name in SECRET_PATTERN.findall(text):
            names.add(dot_name or bracket_name)
    return names


def contains_secret_context(value: Any) -> bool:
    return any(SECRET_CONTEXT_PATTERN.search(text) for text in scalar_strings(value))


def secret_context_is_enumerable(value: Any) -> bool:
    for text in scalar_strings(value):
        static_spans = [match.span() for match in SECRET_PATTERN.finditer(text)]
        for context in SECRET_CONTEXT_PATTERN.finditer(text):
            if not any(start <= context.start() < end for start, end in static_spans):
                return False
    return True


def contains_secrets_inherit(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("secrets") == "inherit":
            return True
        return any(contains_secrets_inherit(child) for child in value.values())
    if isinstance(value, list):
        return any(contains_secrets_inherit(child) for child in value)
    return False


def run_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, dict):
        run = value.get("run")
        if isinstance(run, str):
            values.append(run)
        for child in value.values():
            values.extend(run_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(run_values(child))
    return values


def meaningful_run(run: str) -> str:
    return "\n".join(
        line for line in run.splitlines() if not line.lstrip().startswith("#")
    )


def use_targets(value: Any) -> list[str]:
    targets: list[str] = []
    if isinstance(value, dict):
        target = value.get("uses")
        if isinstance(target, str):
            targets.append(target)
        for child in value.values():
            targets.extend(use_targets(child))
    elif isinstance(value, list):
        for child in value:
            targets.extend(use_targets(child))
    return targets


def value_has_deploy_capability(value: Any) -> bool:
    if any(target.startswith("docker/login-action@") for target in use_targets(value)):
        return True
    patterns = (
        r"\bdocker\s+(?:image\s+)?push\b",
        r"\bdocker\s+buildx\s+build\b[^\n]*\s--push\b",
        r"\bhelm\b",
        r"\brsync\b",
        r"\bkubectl\b",
        r"\b(?:scp|ssh)\b",
    )
    runs = "\n".join(meaningful_run(run) for run in run_values(value))
    return any(re.search(pattern, runs, re.IGNORECASE) for pattern in patterns)


def deploy_capability(document: ParsedYaml) -> bool:
    return value_has_deploy_capability(document.data)


def permission_errors(permissions: Any, *, auxiliary: bool) -> bool:
    if not isinstance(permissions, dict):
        return True
    if auxiliary:
        return permissions.get("contents") != "read" or any(
            ALLOWED_AUX_PERMISSIONS.get(key) != value
            for key, value in permissions.items()
        )
    return permissions != {"contents": "read"}


def line_comment(document: ParsedYaml, line: int) -> str:
    lines = document.text.splitlines()
    if line >= len(lines) or "#" not in lines[line]:
        return ""
    return lines[line].split("#", 1)[1].strip()


def inspect_action_references(documents: Iterable[ParsedYaml]) -> list[str]:
    errors: list[str] = []
    for document in documents:
        for reference in document.uses:
            target = reference.target
            if target.startswith("./") or target.startswith("docker://"):
                continue
            if "@" not in target:
                errors.append(
                    f"[ACTION_PIN] {document.path}: {target} 缺少 @<完整 SHA>"
                )
                continue
            action, revision = target.rsplit("@", 1)
            known = KNOWN_ACTIONS.get(action)
            if known:
                expected_revision, expected_version = known
                if revision != expected_revision:
                    errors.append(
                        f"[ACTION_PIN] {document.path}: {action} 必须锁定 {expected_revision}"
                    )
                if line_comment(document, reference.line) != expected_version:
                    errors.append(
                        f"[ACTION_VERSION] {document.path}: {action} 必须保留 # {expected_version}"
                    )
            else:
                if not FULL_SHA_PATTERN.fullmatch(revision):
                    errors.append(
                        f"[ACTION_PIN] {document.path}: {action} 未锁定 40 位 commit SHA"
                    )
                if not re.fullmatch(
                    r"v\d+(?:\.\d+){0,2}", line_comment(document, reference.line)
                ):
                    errors.append(
                        f"[ACTION_VERSION] {document.path}: {action} 缺少精确版本注释"
                    )
            if action == "actions/checkout":
                with_config = reference.parent.get("with")
                if (
                    not isinstance(with_config, dict)
                    or with_config.get("persist-credentials") != "false"
                ):
                    errors.append(
                        f"[CHECKOUT_CREDENTIAL] {document.path}: checkout 必须结构化设置 persist-credentials:false"
                    )
    return errors


def build_source(repo: str) -> RepositorySource:
    metadata = gh_api(repo, "")
    if not isinstance(metadata, dict):
        raise AuditError("repository metadata 响应无效")
    source = RepositorySource(repo=repo, workflows={}, tree={})
    if metadata.get("default_branch") != "master":
        source.errors.append("[DEFAULT_BRANCH] 仓库 default_branch 必须是 master")

    workflows = gh_api_paginated(repo, "actions/workflows", "workflows")
    for workflow in workflows:
        if workflow.get("state") != "active":
            continue
        path = workflow.get("path")
        if path == "dynamic/dependabot/update-graph":
            continue
        if not isinstance(path, str) or not path.startswith(".github/workflows/"):
            source.errors.append("[WORKFLOW_LIST] active workflow 缺少合法 path")
            continue
        try:
            text = repository_content(repo, path)
        except AuditError as error:
            source.errors.append(
                f"[WORKFLOW_LIST] active workflow {path} 无法从 master 读取：{error}"
            )
            continue
        try:
            source.workflows[path] = parse_yaml(path, text, "workflow")
        except AuditError as error:
            source.errors.append(f"[WORKFLOW_STRUCTURE] {error}")

    tree_payload = gh_api(repo, "git/trees/master?recursive=1")
    if not isinstance(tree_payload, dict) or not isinstance(
        tree_payload.get("tree"), list
    ):
        raise AuditError("master recursive tree 响应无效")
    if tree_payload.get("truncated"):
        source.errors.append(
            "[ACTION_TREE] master recursive tree 被截断，拒绝不完整审计"
        )
    for item in tree_payload["tree"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            source.errors.append("[ACTION_TREE] tree item 结构无效")
            continue
        source.tree[item["path"]] = item

    for path, item in sorted(source.tree.items()):
        if not (
            (
                path == ".github/actions/action.yml"
                or path == ".github/actions/action.yaml"
            )
            or re.match(r"^\.github/actions/.+/action\.ya?ml$", path)
        ):
            continue
        if item.get("type") != "blob" or item.get("mode") == "120000":
            source.errors.append(f"[LOCAL_ACTION] {path} 不是普通文件或属于 symlink")
            continue
        try:
            source.local_actions[path] = parse_yaml(
                path, repository_content(repo, path), "action"
            )
        except AuditError as error:
            source.errors.append(f"[WORKFLOW_STRUCTURE] {error}")
    return source


def normalized_local_target(target: str) -> str:
    if not target.startswith("./"):
        raise AuditError(f"本地 Action 路径必须以 ./ 开头：{target}")
    path = PurePosixPath(target[2:])
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise AuditError(f"本地 Action 路径发生逃逸或无法规范化：{target}")
    return path.as_posix()


def resolve_local_action(source: RepositorySource, target: str) -> ParsedYaml:
    directory = normalized_local_target(target)
    for path, item in source.tree.items():
        if item.get("mode") == "120000" and (
            path == directory or directory.startswith(f"{path}/")
        ):
            raise AuditError(f"{target} 穿过 symlink {path}")
    candidates = [f"{directory}/action.yml", f"{directory}/action.yaml"]
    found = [path for path in candidates if path in source.tree]
    if len(found) != 1:
        raise AuditError(f"{target} 必须且只能解析到一个 action.yml/action.yaml")
    path = found[0]
    item = source.tree[path]
    if item.get("type") != "blob" or item.get("mode") == "120000":
        raise AuditError(f"{path} 不是普通文件或属于 symlink")
    if path not in source.local_actions:
        source.local_actions[path] = parse_yaml(
            path, repository_content(source.repo, path), "action"
        )
    return source.local_actions[path]


def local_action_closure(
    source: RepositorySource, document: ParsedYaml
) -> tuple[list[ParsedYaml], list[str]]:
    resolved: list[ParsedYaml] = []
    errors: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(current: ParsedYaml) -> None:
        for reference in current.uses:
            if not reference.target.startswith("./"):
                continue
            try:
                action = resolve_local_action(source, reference.target)
            except AuditError as error:
                errors.append(f"[LOCAL_ACTION] {current.path}: {error}")
                continue
            if action.path in visiting:
                errors.append(f"[LOCAL_ACTION] 本地 Action 递归引用：{action.path}")
                continue
            if action.path in visited:
                continue
            visiting.add(action.path)
            resolved.append(action)
            visit(action)
            visiting.remove(action.path)
            visited.add(action.path)

    visit(document)
    return resolved, errors


def inspect_primary_pr(source: RepositorySource) -> list[str]:
    errors: list[str] = []
    primary: list[ParsedYaml] = []
    for document in source.workflows.values():
        matching_jobs = [
            job
            for job in jobs_map(document).values()
            if job.get("name") == "PR container validation"
        ]
        if matching_jobs:
            primary.append(document)
    if len(primary) != 1:
        return [f"[PR_CHECK_NAME] 主 PR workflow 必须唯一，当前为 {len(primary)} 个"]

    document = primary[0]
    events = event_map(document)
    pull_request = events.get("pull_request")
    if set(events) != {"pull_request"}:
        errors.append(
            f"[PR_EVENT] {document.path}: 主 PR workflow 只能有 pull_request 事件"
        )
    if not isinstance(pull_request, dict):
        errors.append(f"[PR_EVENT] {document.path}: pull_request 必须显式配置 branches")
    else:
        branches = pull_request.get("branches")
        if branches != ["master"] or "branches-ignore" in pull_request:
            errors.append(
                f"[PR_EVENT] {document.path}: PR branches 必须精确等于 [master]"
            )
    if permission_errors(document.data.get("permissions"), auxiliary=False):
        errors.append(
            f"[PR_PERMISSION] {document.path}: 顶层权限必须精确为 contents: read"
        )
    for job_id, job in jobs_map(document).items():
        if "permissions" in job and permission_errors(
            job["permissions"], auxiliary=False
        ):
            errors.append(
                f"[PR_PERMISSION] {document.path}: job {job_id} 权限超出只读边界"
            )
        if job.get("runs-on") != "ubuntu-latest":
            errors.append(
                f"[PR_RUNNER] {document.path}: job {job_id} 必须使用 ubuntu-latest"
            )
        if "environment" in job:
            errors.append(
                f"[PR_ENVIRONMENT] {document.path}: job {job_id} 不得绑定 Environment"
            )
    closure, closure_errors = local_action_closure(source, document)
    errors.extend(closure_errors)
    documents = [document, *closure]
    if any(contains_secret_context(item.data) for item in documents):
        errors.append(
            f"[PR_SECRET] {document.path}: 主 PR workflow 或其本地 Action 引用了 secret"
        )
    if any(deploy_capability(item) for item in documents):
        errors.append(
            f"[PR_DEPLOY] {document.path}: 主 PR workflow 或其本地 Action 含部署能力"
        )
    errors.extend(inspect_action_references(closure))
    return errors


def inspect_auxiliary_pr(source: RepositorySource) -> list[str]:
    errors: list[str] = []
    for document in source.workflows.values():
        if "pull_request" not in event_map(document):
            continue
        if any(
            job.get("name") == "PR container validation"
            for job in jobs_map(document).values()
        ):
            continue
        closure, closure_errors = local_action_closure(source, document)
        errors.extend(closure_errors)
        documents = [document, *closure]
        if any(contains_secret_context(item.data) for item in documents):
            errors.append(
                f"[AUX_PR_SECRET] {document.path}: 辅助 PR workflow 引用了 secret"
            )
        if any("environment" in job for job in jobs_map(document).values()):
            errors.append(
                f"[AUX_PR_ENVIRONMENT] {document.path}: 辅助 PR workflow 绑定 Environment"
            )
        if any(
            "self-hosted" in list(scalar_strings(job.get("runs-on")))
            for job in jobs_map(document).values()
        ):
            errors.append(
                f"[AUX_PR_RUNNER] {document.path}: 辅助 PR workflow 使用 self-hosted"
            )
        top_permissions = document.data.get("permissions")
        effective_permissions = [
            job.get("permissions", top_permissions)
            for job in jobs_map(document).values()
        ]
        if any(
            permission_errors(item, auxiliary=True) for item in effective_permissions
        ):
            errors.append(
                f"[AUX_PR_PERMISSION] {document.path}: 辅助 PR workflow 权限超出 CodeQL 例外"
            )
        if any(deploy_capability(item) for item in documents):
            errors.append(
                f"[AUX_PR_DEPLOY] {document.path}: 辅助 PR workflow 含部署能力"
            )
        errors.extend(inspect_action_references(closure))
    return errors


def exact_master_push(events: dict[str, Any]) -> bool:
    push = events.get("push")
    return isinstance(push, dict) and push.get("branches") == ["master"]


def needs_ids(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs")
    if isinstance(needs, str):
        return {needs}
    if isinstance(needs, list) and all(isinstance(item, str) for item in needs):
        return set(needs)
    return set()


def master_guarded(job: dict[str, Any]) -> bool:
    condition = job.get("if")
    if not isinstance(condition, str):
        return False
    return bool(
        re.fullmatch(
            r"\s*(?:\$\{\{\s*)?github\.ref\s*==\s*['\"]refs/heads/master['\"](?:\s*\}\})?\s*",
            condition,
        )
    )


def deploy_smoke_ok(job: dict[str, Any]) -> bool:
    runs = "\n".join(meaningful_run(run) for run in run_values(job))
    command_prefix = r"(?:^|[;&|]|\$\()\s*(?:if\s+)?"
    actual_assignments = re.findall(
        r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[^\n]*\$\(\s*docker\s+inspect\b[^\n]*\.Config\.Image[^\n]*\)",
        runs,
    )
    expected_assignments = re.findall(
        r"(?mi)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[^\n]*(?:GITHUB_SHA|github\.sha)[^\n]*$",
        runs,
    )
    if not actual_assignments:
        return False

    def variable_reference(name: str) -> str:
        return rf"(?:\$\{{{re.escape(name)}\}}|\${re.escape(name)})"

    compared = False
    for actual in actual_assignments:
        actual_ref = variable_reference(actual)
        direct_expected = r"[^\n]*(?:GITHUB_SHA|github\.sha)"
        direct_equality = re.search(
            rf"(?mi)^\s*(?:test\s+|\[\[?\s*)[^\n]*(?:{actual_ref}[^\n]*(?:==|=){direct_expected}|(?:GITHUB_SHA|github\.sha)[^\n]*(?:==|=)[^\n]*{actual_ref})",
            runs,
        )
        direct_inequality = re.search(
            rf"(?ms)\bif\b[^\n]*(?:{actual_ref}[^\n]*!={direct_expected}|(?:GITHUB_SHA|github\.sha)[^\n]*!=[^\n]*{actual_ref})[^\n]*(?:;\s*then|\n\s*then).*?\bexit\s+[1-9]\b.*?\bfi\b",
            runs,
        )
        if direct_equality or direct_inequality:
            compared = True
            break
        for expected in expected_assignments:
            expected_ref = variable_reference(expected)
            left_right = rf"{actual_ref}[^\n]*(?:==|=)[^\n]*{expected_ref}"
            right_left = rf"{expected_ref}[^\n]*(?:==|=)[^\n]*{actual_ref}"
            equality = re.search(
                rf"(?m)^\s*(?:test\s+|\[\[?\s*)[^\n]*(?:{left_right}|{right_left})",
                runs,
            )
            inequality = re.search(
                rf"(?ms)\bif\b[^\n]*(?:{actual_ref}[^\n]*!=[^\n]*{expected_ref}|{expected_ref}[^\n]*!=[^\n]*{actual_ref})[^\n]*(?:;\s*then|\n\s*then).*?\bexit\s+[1-9]\b.*?\bfi\b",
                runs,
            )
            if equality or inequality:
                compared = True
                break
        if compared:
            break
    return compared and bool(
        re.search(command_prefix + r"docker\s+exec\b", runs, re.MULTILINE)
    )


def inspect_release(source: RepositorySource) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    candidates = [
        document
        for document in source.workflows.values()
        if "push" in event_map(document)
        and any(environment_name(job) == "dev" for job in jobs_map(document).values())
    ]
    if len(candidates) != 1:
        return [
            f"[RELEASE_WORKFLOW] dev master 发布 workflow 必须唯一，当前为 {len(candidates)} 个"
        ], set()
    document = candidates[0]
    events = event_map(document)
    if not exact_master_push(events) or not set(events).issubset(
        {"push", "workflow_dispatch"}
    ):
        errors.append(
            f"[RELEASE_EVENT] {document.path}: 发布事件必须是 master push 与可选 workflow_dispatch"
        )
    if permission_errors(document.data.get("permissions"), auxiliary=False):
        errors.append(
            f"[RELEASE_PERMISSION] {document.path}: 顶层权限必须精确为 contents: read"
        )
    if contains_secret_context(document.data.get("env", {})):
        errors.append(
            f"[SECRET_ENV_BOUNDARY] {document.path}: 顶层 env 不得引用 secret"
        )

    jobs = jobs_map(document)
    referenced: set[str] = set()
    publish_jobs: set[str] = set()
    deploy_jobs: set[str] = set()
    for job_id, job in jobs.items():
        if contains_secrets_inherit(job) or (
            contains_secret_context(job) and not secret_context_is_enumerable(job)
        ):
            errors.append(
                f"[SECRET_ENV_BOUNDARY] {document.path}: job {job_id} 的 secret context 无法完整静态列举或使用 inherit"
            )
        job_secrets = referenced_secret_names(job) - ALLOWED_IMPLICIT_SECRETS
        referenced.update(job_secrets)
        if job_secrets and environment_name(job) != "dev":
            errors.append(
                f"[SECRET_ENV_BOUNDARY] {document.path}: job {job_id} 引用 secret 但未绑定 dev"
            )
        if environment_name(job) != "dev":
            continue
        if deployment_false(job):
            publish_jobs.add(job_id)
        else:
            deploy_jobs.add(job_id)

    privileged_publish_jobs = {
        job_id for job_id in publish_jobs if value_has_deploy_capability(jobs[job_id])
    }
    if not privileged_publish_jobs:
        errors.append(
            "[PUBLISH_ENVIRONMENT] 未找到含登录或 push 能力的真实 dev/deployment:false 发布 job"
        )
    if not deploy_jobs:
        errors.append("[DEPLOY_ENVIRONMENT] 未找到 dev 部署 job")
    for job_id in deploy_jobs:
        if not deploy_smoke_ok(jobs[job_id]):
            errors.append(
                f"[DEPLOY_SMOKE] {document.path}: deploy job {job_id} 缺少真实容器内 smoke/镜像身份核验"
            )

    if "workflow_dispatch" in events:
        guarded: set[str] = {
            job_id for job_id, job in jobs.items() if master_guarded(job)
        }
        changed = True
        while changed:
            changed = False
            for job_id, job in jobs.items():
                if job_id in guarded:
                    continue
                if "if" in job:
                    continue
                dependencies = needs_ids(job)
                if dependencies and dependencies.issubset(guarded):
                    guarded.add(job_id)
                    changed = True
        privileged = privileged_publish_jobs | deploy_jobs
        if not privileged.issubset(guarded):
            errors.append(
                f"[RELEASE_EVENT] {document.path}: 手动发布的高权限 job 未由结构化 master guard/needs 链保护"
            )
    return errors, referenced


def inspect_protection(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["[BRANCH_PROTECTION] master protection 响应无效"]
    errors: list[str] = []
    required = payload.get("required_status_checks")
    if not isinstance(required, dict):
        return ["[BRANCH_PROTECTION] required_status_checks 结构无效"]
    if required.get("strict") is not True:
        errors.append("[BRANCH_PROTECTION] required status checks 未启用 strict")
    checks = required.get("checks")
    if not isinstance(checks, list):
        errors.append("[REQUIRED_CHECK_APP] required_status_checks.checks 必须是数组")
        checks = []
    contexts = {check.get("context") for check in checks if isinstance(check, dict)}
    if "PR container validation" not in contexts:
        legacy_contexts = required.get("contexts")
        if (
            not isinstance(legacy_contexts, list)
            or "PR container validation" not in legacy_contexts
        ):
            errors.append("[REQUIRED_CHECK] master 未要求 PR container validation")
        errors.append("[REQUIRED_CHECK_APP] checks 中缺少 PR container validation")
    elif not any(
        isinstance(check, dict)
        and check.get("context") == "PR container validation"
        and check.get("app_id") == 15368
        for check in checks
    ):
        errors.append(
            "[REQUIRED_CHECK_APP] PR container validation 必须绑定 app_id=15368"
        )
    if payload.get("required_pull_request_reviews") is None:
        errors.append("[BRANCH_PROTECTION] master 未要求 Pull Request review")
    if (payload.get("enforce_admins") or {}).get("enabled") is not True:
        errors.append("[BRANCH_PROTECTION] master 未对管理员执行保护")
    if (payload.get("required_conversation_resolution") or {}).get(
        "enabled"
    ) is not True:
        errors.append("[BRANCH_PROTECTION] master 未要求解决对话")
    if (payload.get("allow_force_pushes") or {}).get("enabled") is not False:
        errors.append("[BRANCH_PROTECTION] master 仍允许 force push")
    if (payload.get("allow_deletions") or {}).get("enabled") is not False:
        errors.append("[BRANCH_PROTECTION] master 仍允许删除")
    return errors


def secret_names(items: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in items:
        name = item.get("name")
        if not isinstance(name, str):
            raise AuditError("secret 元数据缺少 name")
        names.add(name)
    return names


def audit_repository(repo: str) -> list[str]:
    try:
        source = build_source(repo)
        errors = list(source.errors)
        if not source.workflows:
            errors.append("[WORKFLOW_LIST] 未找到可解析的 active workflow")
        errors.extend(inspect_action_references(source.workflows.values()))
        errors.extend(inspect_action_references(source.local_actions.values()))
        errors.extend(inspect_primary_pr(source))
        errors.extend(inspect_auxiliary_pr(source))
        release_errors, referenced_secrets = inspect_release(source)
        errors.extend(release_errors)
        errors.extend(inspect_protection(gh_api(repo, "branches/master/protection")))

        environment = gh_api(repo, "environments/dev", optional=True)
        if environment is None:
            errors.append("[DEV_ENVIRONMENT] 缺少 dev Environment 或当前身份无权读取")
            environment_secret_names: set[str] = set()
        else:
            environment_secret_names = secret_names(
                gh_api_paginated(repo, "environments/dev/secrets", "secrets")
            )
        repository_secret_names = secret_names(
            gh_api_paginated(repo, "actions/secrets", "secrets")
        )
        missing = referenced_secrets - environment_secret_names
        if missing:
            errors.append(
                "[ENV_SECRET_BOUNDARY] active release 引用但 dev Environment 缺少："
                + ", ".join(sorted(missing))
            )
        if repository_secret_names:
            errors.append(
                "[REPO_SECRET_BOUNDARY] repository scope 仍有 secret 名称："
                + ", ".join(sorted(repository_secret_names))
            )
        return errors
    except AuditError as error:
        return [f"[API] {error}"]


def main(repositories: list[str]) -> int:
    invalid = [repo for repo in repositories if not REPO_PATTERN.fullmatch(repo)]
    if invalid:
        for repo in invalid:
            print(f"FAIL {repo}")
            print("  [ARGUMENT] 仓库必须使用 owner/repo 格式")
        return 2
    failed = 0
    for repo in repositories:
        errors = audit_repository(repo)
        if errors:
            failed += 1
            print(f"FAIL {repo}")
            for error in errors:
                print(f"  {error}")
        else:
            print(f"PASS {repo}")
    print(f"审计完成：{len(repositories) - failed} 个通过，{failed} 个失败")
    return 1 if failed else 0


raise SystemExit(main(sys.argv[1:]))
