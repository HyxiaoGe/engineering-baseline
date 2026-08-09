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

from markdown_it import MarkdownIt
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
SEMANTIC_ID_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
REPOSITORY_PATH_PATTERN = re.compile(
    r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+$"
)
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
CODE_REVIEW_RULES_HEADING = "## Code Review Rules"
COMMONMARK_PARSER = MarkdownIt("commonmark")


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
    release_manifest: ParsedYaml | None = None
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ReleaseSafetyManifest:
    workflow_path: str
    contract_test_path: str
    contract_test_step: str
    jobs: dict[str, str | None]
    target_job: str
    steps: dict[str, str | list[str] | None]
    needs: dict[str, list[str]]
    conditions: dict[str, str | None]


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
        r"\bdocker\s+(?:image\s+)?pull\b",
        r"\bdocker\s+buildx\s+build\b[^\n]*\s--push\b",
        r"\bdocker\s+compose\s+(?:up|down|restart|pull)\b",
        r"(?:^|[/\\])(?:ci-)?(?:deploy|rollback)(?:[-_.][A-Za-z0-9_-]+)*\.(?:sh|ps1)\b",
        r"\bhelm\b",
        r"\brsync\b",
        r"\bkubectl\b",
        r"\b(?:scp|ssh)\b",
    )
    runs = "\n".join(meaningful_run(run) for run in run_values(value))
    return any(re.search(pattern, runs, re.IGNORECASE) for pattern in patterns)


def deploy_capability(document: ParsedYaml) -> bool:
    return value_has_deploy_capability(document.data)


def uses_self_hosted(job: dict[str, Any]) -> bool:
    return "self-hosted" in set(scalar_strings(job.get("runs-on")))


def release_capability_signals(
    source: RepositorySource, document: ParsedYaml
) -> set[str]:
    jobs = jobs_map(document)
    signals: set[str] = set()
    if any(environment_name(job) == "dev" for job in jobs.values()):
        signals.add("dev Environment")
    if any(uses_self_hosted(job) for job in jobs.values()):
        signals.add("self-hosted runner")
    if contains_secret_context(document.data):
        signals.add("secret")
    if value_has_deploy_capability(document.data):
        signals.add("deploy command")
    closure, closure_errors = local_action_closure(source, document)
    if closure_errors:
        signals.add("unresolved local Action")
    if any(contains_secret_context(action.data) for action in closure):
        signals.add("local Action secret")
    if any(value_has_deploy_capability(action.data) for action in closure):
        signals.add("local Action deploy command")
    if "workflow_dispatch" in event_map(document) and signals:
        signals.add("manual trigger")
    return signals


def release_job_capability_signals(
    source: RepositorySource, document: ParsedYaml, job: dict[str, Any]
) -> set[str]:
    signals: set[str] = set()
    if uses_self_hosted(job):
        signals.add("self-hosted runner")
    if "environment" in job:
        signals.add("Environment")
    if contains_secret_context(job):
        signals.add("secret")
    if value_has_deploy_capability(job):
        signals.add("deploy command")
    job_mapping_ids = {id(mapping) for mapping in walk_mappings(job)}
    local_document = ParsedYaml(
        path=document.path,
        text=document.text,
        data=job,
        uses=[
            reference
            for reference in document.uses
            if id(reference.parent) in job_mapping_ids
        ],
        kind="workflow",
    )
    closure, closure_errors = local_action_closure(source, local_document)
    if closure_errors:
        signals.add("unresolved local Action")
    if any(contains_secret_context(action.data) for action in closure):
        signals.add("local Action secret")
    if any(value_has_deploy_capability(action.data) for action in closure):
        signals.add("local Action deploy command")
    return signals


def permission_errors(permissions: Any, *, auxiliary: bool) -> bool:
    if not isinstance(permissions, dict):
        return True
    if auxiliary:
        return permissions.get("contents") != "read" or any(
            ALLOWED_AUX_PERMISSIONS.get(key) != value
            for key, value in permissions.items()
        )
    return permissions != {"contents": "read"}


def release_job_permissions_safe(permissions: Any) -> bool:
    if not isinstance(permissions, dict):
        return False
    return all(
        value == "none" or (key == "contents" and value == "read")
        for key, value in permissions.items()
    )


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
            if target.startswith("./"):
                continue
            if target.startswith("docker://"):
                if not re.fullmatch(r"docker://[^\s@]+@sha256:[0-9a-f]{64}", target):
                    errors.append(
                        f"[ACTION_PIN] {document.path}: docker Action 必须锁定 sha256 内容摘要"
                    )
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
    if metadata.get("allow_auto_merge") is not True:
        source.errors.append(
            "[REPOSITORY_MERGE_POLICY] 仓库必须允许对单个 PR 使用 Auto-merge"
        )
    if metadata.get("delete_branch_on_merge") is not True:
        source.errors.append(
            "[REPOSITORY_MERGE_POLICY] 仓库必须在合并后自动删除远端功能分支"
        )

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

    manifest_path = ".github/release-safety.yml"
    manifest_item = source.tree.get(manifest_path)
    if manifest_item is None:
        source.errors.append(
            f"[RELEASE_MANIFEST] master 缺少声明式适配文件 {manifest_path}"
        )
    elif manifest_item.get("type") != "blob" or manifest_item.get("mode") == "120000":
        source.errors.append(
            f"[RELEASE_MANIFEST] {manifest_path} 不是普通文件或属于 symlink"
        )
    else:
        try:
            source.release_manifest = parse_yaml(
                manifest_path,
                repository_content(repo, manifest_path),
                "manifest",
            )
        except AuditError as error:
            source.errors.append(f"[RELEASE_MANIFEST] {error}")
    return source


def normalized_local_target(target: str) -> str:
    if not target.startswith("./"):
        raise AuditError(f"本地 Action 路径必须以 ./ 开头：{target}")
    path = PurePosixPath(target[2:])
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise AuditError(f"本地 Action 路径发生逃逸或无法规范化：{target}")
    return path.as_posix()


def has_code_review_rules_heading(text: str) -> bool:
    source_lines = text.splitlines()
    for token in COMMONMARK_PARSER.parse(text):
        if token.type != "heading_open" or token.tag != "h2" or token.map is None:
            continue
        start_line = token.map[0]
        if (
            start_line < len(source_lines)
            and source_lines[start_line] == CODE_REVIEW_RULES_HEADING
        ):
            return True
    return False


def inspect_code_review_rules(source: RepositorySource) -> list[str]:
    path = "AGENTS.md"
    item = source.tree.get(path)
    if item is None:
        return [f"[CODE_REVIEW_RULES] master 缺少根级 {path}"]
    if item.get("type") != "blob" or item.get("mode") not in {"100644", "100755"}:
        return [f"[CODE_REVIEW_RULES] 根级 {path} 不是普通文件或属于 symlink"]
    try:
        text = repository_content(source.repo, path)
    except AuditError as error:
        return [f"[CODE_REVIEW_RULES] 无法从 master 读取根级 {path}：{error}"]
    if not has_code_review_rules_heading(text):
        return [
            f"[CODE_REVIEW_RULES] 根级 {path} 缺少精确标题 {CODE_REVIEW_RULES_HEADING}"
        ]
    return []


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


def normalized_condition(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    condition = value.strip()
    if condition.startswith("${{") and condition.endswith("}}"):
        condition = condition[3:-2].strip()
    return re.sub(r"\s+", " ", condition)


def strip_outer_parentheses(expression: str) -> str:
    value = expression.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        quote_char = ""
        closes_at_end = False
        for index, char in enumerate(value):
            if quote_char:
                if char == quote_char and (index == 0 or value[index - 1] != "\\"):
                    quote_char = ""
                continue
            if char in ("'", '"'):
                quote_char = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    closes_at_end = index == len(value) - 1
                    break
        if not closes_at_end:
            break
        value = value[1:-1].strip()
    return value


def split_top_level(expression: str, operator: str) -> list[str]:
    value = strip_outer_parentheses(expression)
    parts: list[str] = []
    depth = 0
    quote_char = ""
    start = 0
    index = 0
    while index < len(value):
        char = value[index]
        if quote_char:
            if char == quote_char and (index == 0 or value[index - 1] != "\\"):
                quote_char = ""
            index += 1
            continue
        if char in ("'", '"'):
            quote_char = char
            index += 1
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            depth -= 1
            index += 1
            continue
        if depth == 0 and value.startswith(operator, index):
            parts.append(value[start:index].strip())
            index += len(operator)
            start = index
            continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:].strip())
    return parts


def flatten_conjunction(expression: str) -> list[str] | None:
    value = strip_outer_parentheses(expression)
    if len(split_top_level(value, "||")) > 1:
        return None
    parts = split_top_level(value, "&&")
    if len(parts) == 1:
        return [value]
    flattened: list[str] = []
    for part in parts:
        child = flatten_conjunction(part)
        if child is None:
            return None
        flattened.extend(child)
    return flattened


def top_level_conjuncts(expression: str) -> list[str]:
    return [strip_outer_parentheses(part) for part in split_top_level(expression, "&&")]


def is_master_guard_atom(expression: str) -> bool:
    return bool(
        re.fullmatch(
            r"github\.ref\s*==\s*(['\"])refs/heads/master\1",
            strip_outer_parentheses(expression),
        )
    )


def is_function_atom(expression: str, name: str) -> bool:
    return bool(
        re.fullmatch(
            rf"{re.escape(name)}\s*\(\s*\)", strip_outer_parentheses(expression)
        )
    )


def is_non_dispatch_atom(expression: str) -> bool:
    return bool(
        re.fullmatch(
            r"github\.event_name\s*(?:!=\s*(['\"])workflow_dispatch\1|==\s*(['\"])push\2)",
            strip_outer_parentheses(expression),
        )
    )


def is_dispatch_atom(expression: str) -> bool:
    return bool(
        re.fullmatch(
            r"github\.event_name\s*==\s*(['\"])workflow_dispatch\1",
            strip_outer_parentheses(expression),
        )
    )


def signal_negative_atom(expression: str, signal: str, *, dispatch: bool) -> bool:
    atom = strip_outer_parentheses(expression)
    escaped = re.escape(signal)
    if dispatch:
        return bool(re.fullmatch(rf"{escaped}\s*==\s*(['\"])\1", atom))
    return bool(
        re.fullmatch(rf"{escaped}\s*!=\s*(['\"])true\1", atom)
        or re.fullmatch(rf"{escaped}\s*==\s*(['\"])false\1", atom)
    )


def signal_positive_atom(expression: str, signal: str, *, dispatch: bool) -> bool:
    atom = strip_outer_parentheses(expression)
    escaped = re.escape(signal)
    if dispatch:
        return bool(re.fullmatch(rf"{escaped}\s*!=\s*(['\"])\1", atom))
    return bool(re.fullmatch(rf"{escaped}\s*==\s*(['\"])true\1", atom))


def rollback_negative_condition_safe(
    condition: str, signal: str, *, dispatch: bool
) -> bool:
    if signal_negative_atom(condition, signal, dispatch=dispatch):
        return True
    if not dispatch:
        return False
    branches = split_top_level(condition, "||")
    if len(branches) != 2:
        return False
    return (
        is_non_dispatch_atom(branches[0])
        and signal_negative_atom(branches[1], signal, dispatch=True)
    ) or (
        is_non_dispatch_atom(branches[1])
        and signal_negative_atom(branches[0], signal, dispatch=True)
    )


def publish_rollback_signal(
    condition: str, signals: set[str], *, dispatch: bool
) -> str | None:
    terms = top_level_conjuncts(condition)
    if len(terms) != 2 or sum(is_master_guard_atom(term) for term in terms) != 1:
        return None
    guard = next(term for term in terms if not is_master_guard_atom(term))
    matches = [
        signal
        for signal in signals
        if rollback_negative_condition_safe(guard, signal, dispatch=dispatch)
    ]
    return matches[0] if len(matches) == 1 else None


def is_needs_result_atom(expression: str, job_id: str, result: str) -> bool:
    return bool(
        re.fullmatch(
            rf"needs\.{re.escape(job_id)}\.result\s*==\s*(['\"]){re.escape(result)}\1",
            strip_outer_parentheses(expression),
        )
    )


def deploy_branch_kind(
    branch: str,
    publish_job_id: str,
    signal: str,
    *,
    dispatch: bool,
) -> str | None:
    atoms = flatten_conjunction(branch)
    if atoms is None:
        return None
    atoms = [strip_outer_parentheses(atom) for atom in atoms]
    publish_success = [
        atom for atom in atoms if is_needs_result_atom(atom, publish_job_id, "success")
    ]
    publish_skipped = [
        atom for atom in atoms if is_needs_result_atom(atom, publish_job_id, "skipped")
    ]
    negative = [
        atom for atom in atoms if signal_negative_atom(atom, signal, dispatch=dispatch)
    ]
    positive = [
        atom for atom in atoms if signal_positive_atom(atom, signal, dispatch=dispatch)
    ]
    dispatch_atoms = [atom for atom in atoms if is_dispatch_atom(atom)]
    if len(publish_success) == 1 and not publish_skipped and not positive:
        allowed = publish_success + negative
        if len(negative) <= 1 and len(atoms) == len(allowed):
            return "normal"
    required_dispatch = 1 if dispatch else 0
    if (
        not publish_success
        and not negative
        and len(publish_skipped) == 1
        and len(positive) == 1
        and len(dispatch_atoms) == required_dispatch
        and len(atoms) == 2 + required_dispatch
    ):
        return "rollback"
    return None


def deploy_has_explicit_paths(
    condition: str,
    publish_job_id: str,
    signal: str,
    *,
    dispatch: bool,
    prepare_job_id: str | None,
) -> bool:
    terms = top_level_conjuncts(condition)
    special_terms: list[str] = []
    other_terms: list[str] = []
    for term in terms:
        branches = split_top_level(term, "||")
        if len(branches) == 2:
            special_terms.append(term)
        else:
            other_terms.append(term)
    if len(special_terms) != 1:
        return False
    always_terms = [term for term in other_terms if is_function_atom(term, "always")]
    master_terms = [term for term in other_terms if is_master_guard_atom(term)]
    if len(always_terms) != 1 or len(master_terms) != 1:
        return False
    recognized = always_terms + master_terms
    if prepare_job_id is not None:
        prepare_results = [
            term
            for term in other_terms
            if is_needs_result_atom(term, prepare_job_id, "success")
        ]
        if len(prepare_results) != 1:
            return False
        recognized.extend(prepare_results)
    if len(recognized) != len(other_terms):
        return False
    branches = split_top_level(special_terms[0], "||")
    kinds = [
        deploy_branch_kind(
            branch,
            publish_job_id,
            signal,
            dispatch=dispatch,
        )
        for branch in branches
    ]
    return (
        sorted(kind for kind in kinds if kind is not None)
        == [
            "normal",
            "rollback",
        ]
        and None not in kinds
    )


def rollback_condition_safe(
    condition: str, capture_step_id: str, candidate_step_id: str
) -> bool:
    atoms = flatten_conjunction(condition)
    if atoms is None:
        return False
    normalized_atoms = [strip_outer_parentheses(atom) for atom in atoms]
    failure_atoms = [
        atom for atom in normalized_atoms if is_function_atom(atom, "failure")
    ]
    capture_atoms = [
        atom
        for atom in normalized_atoms
        if re.fullmatch(
            rf"steps\.{re.escape(capture_step_id)}\.outcome\s*==\s*(['\"])success\1",
            atom,
        )
    ]
    candidate_atoms = [
        atom
        for atom in normalized_atoms
        if re.fullmatch(
            rf"steps\.{re.escape(candidate_step_id)}\.outcome\s*!=\s*(['\"])skipped\1",
            atom,
        )
        or re.fullmatch(
            rf"steps\.{re.escape(candidate_step_id)}\.outputs\.entered\s*==\s*(['\"])true\1",
            atom,
        )
    ]
    return (
        len(normalized_atoms) == 3
        and len(failure_atoms) == 1
        and len(capture_atoms) == 1
        and len(candidate_atoms) == 1
    )


def continue_on_error_disabled(step: dict[str, Any]) -> bool:
    if "continue-on-error" not in step:
        return True
    value = step["continue-on-error"]
    if value in (False, "false"):
        return True
    return isinstance(value, str) and bool(
        re.fullmatch(r"\$\{\{\s*false\s*\}\}", value, re.IGNORECASE)
    )


def strict_continue_on_error_disabled(mapping: dict[str, Any]) -> bool:
    if "continue-on-error" not in mapping:
        return True
    value = mapping["continue-on-error"]
    return value is False or (
        isinstance(value, str) and value.strip().lower() == "false"
    )


def has_unsafe_run_defaults(mapping: dict[str, Any]) -> bool:
    defaults = mapping.get("defaults")
    if defaults is None:
        return False
    if not isinstance(defaults, dict):
        return True
    run_defaults = defaults.get("run")
    if run_defaults is None:
        return False
    return not isinstance(run_defaults, dict) or bool(
        {"shell", "working-directory"} & set(run_defaults)
    )


def github_expressions(group: str) -> tuple[list[str], str] | None:
    expressions: list[str] = []
    literals: list[str] = []
    index = 0
    while index < len(group):
        start = group.find("${{", index)
        if start < 0:
            literals.append(group[index:])
            break
        literals.append(group[index:start])
        cursor = start + 3
        quote_char = ""
        while cursor < len(group) - 1:
            char = group[cursor]
            if quote_char:
                if char == quote_char and group[cursor - 1] != "\\":
                    quote_char = ""
                cursor += 1
                continue
            if char in ("'", '"'):
                quote_char = char
                cursor += 1
                continue
            if group.startswith("}}", cursor):
                break
            cursor += 1
        if cursor >= len(group) - 1 or not group.startswith("}}", cursor):
            return None
        expressions.append(group[start + 3 : cursor].strip())
        index = cursor + 2
    remainder = "".join(literals)
    if "${{" in remainder or "}}" in remainder:
        return None
    return expressions, remainder


def format_expression_safe(expression: str, allowed: set[str]) -> bool:
    match = re.fullmatch(r"format\s*\((.*)\)", expression, re.DOTALL)
    if not match:
        return False
    arguments = split_top_level(match.group(1), ",")
    if len(arguments) < 2:
        return False
    literal = arguments[0].strip()
    if not re.fullmatch(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", literal):
        return False
    return all(argument.strip() in allowed for argument in arguments[1:])


def concurrency_group_safe(group: str) -> bool:
    allowed = {
        "github.repository",
        "github.workflow",
        "github.ref",
        "github.ref_name",
    }
    extracted = github_expressions(group)
    if extracted is None:
        return False
    expressions, _ = extracted
    return all(
        expression in allowed or format_expression_safe(expression, allowed)
        for expression in expressions
    )


def step_ids(job: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], bool]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicate = False
    steps = job.get("steps")
    if not isinstance(steps, list):
        return indexed, duplicate
    for step in steps:
        step_id = step.get("id")
        if not isinstance(step_id, str):
            continue
        if step_id in indexed:
            duplicate = True
        indexed[step_id] = step
    return indexed, duplicate


def step_position(job: dict[str, Any], step_id: str) -> int:
    steps = job.get("steps")
    if not isinstance(steps, list):
        return -1
    return next(
        (index for index, step in enumerate(steps) if step.get("id") == step_id),
        -1,
    )


def optional_semantic_id(value: Any, label: str) -> str | None:
    if value in (None, "", "null", "~"):
        return None
    if not isinstance(value, str) or not SEMANTIC_ID_PATTERN.fullmatch(value):
        raise AuditError(f"{label} 必须是合法 ID 或 null")
    return value


def required_semantic_id(value: Any, label: str) -> str:
    result = optional_semantic_id(value, label)
    if result is None:
        raise AuditError(f"{label} 不得为空")
    return result


def semantic_id_list(value: Any, label: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list):
        raise AuditError(f"{label} 必须是 ID 数组")
    result = [required_semantic_id(item, label) for item in value]
    if not allow_empty and not result:
        raise AuditError(f"{label} 不得为空")
    if len(result) != len(set(result)):
        raise AuditError(f"{label} 含重复 ID")
    return result


def optional_condition(value: Any, label: str) -> str | None:
    if value in (None, "", "null", "~"):
        return None
    if not isinstance(value, str) or not normalized_condition(value):
        raise AuditError(f"{label} 必须是非空 condition 或 null")
    return normalized_condition(value)


def parse_release_safety_manifest(document: ParsedYaml) -> ReleaseSafetyManifest:
    data = document.data
    expected_top = {
        "version",
        "workflow",
        "contract_test",
        "jobs",
        "steps",
        "needs",
        "conditions",
    }
    if set(data) != expected_top or data.get("version") != "1":
        raise AuditError("manifest 顶层 schema 或 version 无效")
    workflow_path = data.get("workflow")
    if (
        not isinstance(workflow_path, str)
        or not workflow_path.startswith(".github/workflows/")
        or not REPOSITORY_PATH_PATTERN.fullmatch(workflow_path)
    ):
        raise AuditError("workflow 必须指向仓库内 .github/workflows 文件")

    contract = data.get("contract_test")
    if not isinstance(contract, dict) or set(contract) != {"path", "pr_step"}:
        raise AuditError("contract_test schema 无效")
    contract_path = contract.get("path")
    if not isinstance(contract_path, str) or not REPOSITORY_PATH_PATTERN.fullmatch(
        contract_path
    ):
        raise AuditError("contract_test.path 必须是仓库内相对路径")
    contract_step = required_semantic_id(
        contract.get("pr_step"), "contract_test.pr_step"
    )

    raw_jobs = data.get("jobs")
    expected_jobs = {"prepare", "publish", "deploy", "finalize"}
    if not isinstance(raw_jobs, dict) or set(raw_jobs) != expected_jobs:
        raise AuditError("jobs 必须精确声明 prepare/publish/deploy/finalize")
    jobs: dict[str, str | None] = {
        "prepare": optional_semantic_id(raw_jobs["prepare"], "jobs.prepare"),
        "publish": required_semantic_id(raw_jobs["publish"], "jobs.publish"),
        "deploy": required_semantic_id(raw_jobs["deploy"], "jobs.deploy"),
        "finalize": optional_semantic_id(raw_jobs["finalize"], "jobs.finalize"),
    }
    concrete_jobs = [value for value in jobs.values() if value is not None]
    if len(concrete_jobs) != len(set(concrete_jobs)):
        raise AuditError("jobs 语义角色引用了重复 job ID")

    raw_steps = data.get("steps")
    expected_steps = {
        "target",
        "target_job",
        "capture",
        "migrations",
        "candidate",
        "verify",
        "rollback",
        "cleanup",
        "failure",
        "finalize",
        "finalize_failure",
    }
    if not isinstance(raw_steps, dict) or set(raw_steps) != expected_steps:
        raise AuditError("steps 语义角色 schema 无效")
    steps: dict[str, str | list[str] | None] = {
        "target": required_semantic_id(raw_steps["target"], "steps.target"),
        "capture": required_semantic_id(raw_steps["capture"], "steps.capture"),
        "migrations": semantic_id_list(
            raw_steps["migrations"], "steps.migrations", allow_empty=True
        ),
        "candidate": required_semantic_id(raw_steps["candidate"], "steps.candidate"),
        "verify": semantic_id_list(
            raw_steps["verify"], "steps.verify", allow_empty=False
        ),
        "rollback": required_semantic_id(raw_steps["rollback"], "steps.rollback"),
        "cleanup": required_semantic_id(raw_steps["cleanup"], "steps.cleanup"),
        "failure": optional_semantic_id(raw_steps["failure"], "steps.failure"),
        "finalize": optional_semantic_id(raw_steps["finalize"], "steps.finalize"),
        "finalize_failure": optional_semantic_id(
            raw_steps["finalize_failure"], "steps.finalize_failure"
        ),
    }
    target_job = raw_steps["target_job"]
    if target_job not in {"prepare", "deploy"}:
        raise AuditError("steps.target_job 必须是 prepare 或 deploy")
    if target_job == "prepare" and jobs["prepare"] is None:
        raise AuditError("prepare 为 null 时 target_job 必须是 deploy")
    if jobs["finalize"] is None and any(
        steps[key] is not None for key in ("finalize", "finalize_failure")
    ):
        raise AuditError("finalize job 为 null 时 finalize steps 也必须为 null")
    deploy_step_ids = [
        steps["target"] if target_job == "deploy" else None,
        steps["capture"],
        *steps["migrations"],
        steps["candidate"],
        *steps["verify"],
        steps["rollback"],
        steps["cleanup"],
        steps["failure"],
    ]
    concrete_steps = [value for value in deploy_step_ids if isinstance(value, str)]
    if len(concrete_steps) != len(set(concrete_steps)):
        raise AuditError("deploy 语义角色引用了重复 step ID")
    finalize_steps = [
        value
        for value in (steps["finalize"], steps["finalize_failure"])
        if isinstance(value, str)
    ]
    if len(finalize_steps) != len(set(finalize_steps)):
        raise AuditError("finalize 语义角色引用了重复 step ID")

    raw_needs = data.get("needs")
    expected_needs = {"publish", "deploy", "finalize"}
    if not isinstance(raw_needs, dict) or set(raw_needs) != expected_needs:
        raise AuditError("needs 必须精确声明 publish/deploy/finalize")
    needs: dict[str, list[str]] = {}
    allowed_need_roles = {"prepare", "publish", "deploy"}
    for role in expected_needs:
        values = raw_needs[role]
        if not isinstance(values, list) or any(
            value not in allowed_need_roles for value in values
        ):
            raise AuditError(f"needs.{role} 必须是语义 job role 数组")
        if len(values) != len(set(values)):
            raise AuditError(f"needs.{role} 含重复 role")
        if any(jobs[value] is None for value in values):
            raise AuditError(f"needs.{role} 引用了 null job role")
        needs[role] = values
    if jobs["finalize"] is None and needs["finalize"]:
        raise AuditError("finalize 为 null 时 needs.finalize 必须为空")

    raw_conditions = data.get("conditions")
    expected_conditions = {
        "prepare",
        "publish",
        "deploy",
        "migration",
        "rollback",
        "cleanup",
        "failure",
        "finalize",
        "finalize_failure",
    }
    if not isinstance(raw_conditions, dict) or set(raw_conditions) != (
        expected_conditions
    ):
        raise AuditError("conditions 语义角色 schema 无效")
    conditions = {
        role: optional_condition(raw_conditions[role], f"conditions.{role}")
        for role in expected_conditions
    }
    for role in ("publish", "deploy", "rollback", "cleanup"):
        if conditions[role] is None:
            raise AuditError(f"conditions.{role} 不得为空")
    if jobs["prepare"] is None and conditions["prepare"] is not None:
        raise AuditError("prepare job 为 null 时 condition 也必须为 null")
    if bool(steps["migrations"]) != (conditions["migration"] is not None):
        raise AuditError("migration steps 与 condition 必须同时存在或同时为空")
    if (steps["failure"] is None) != (conditions["failure"] is None):
        raise AuditError("failure step 与 condition 必须同时存在或同时为空")
    if jobs["finalize"] is None and any(
        conditions[role] is not None for role in ("finalize", "finalize_failure")
    ):
        raise AuditError("finalize 为 null 时 finalize conditions 也必须为 null")
    if jobs["finalize"] is not None and conditions["finalize"] is None:
        raise AuditError("finalize job 存在时 conditions.finalize 不得为空")
    if (steps["finalize_failure"] is None) != (conditions["finalize_failure"] is None):
        raise AuditError("finalize_failure step 与 condition 必须同时存在或同时为空")

    return ReleaseSafetyManifest(
        workflow_path=workflow_path,
        contract_test_path=contract_path,
        contract_test_step=contract_step,
        jobs=jobs,
        target_job=target_job,
        steps=steps,
        needs=needs,
        conditions=conditions,
    )


def step_reference(
    job: dict[str, Any], step_id: str, label: str
) -> tuple[dict[str, Any] | None, list[str]]:
    indexed, duplicate = step_ids(job)
    if duplicate:
        return None, [f"[RELEASE_MANIFEST] {label} 所在 job 含重复 step ID"]
    step = indexed.get(step_id)
    if step is None:
        return None, [f"[RELEASE_MANIFEST] {label} 引用不存在的 step：{step_id}"]
    return step, []


def inspect_contract_test(
    source: RepositorySource, manifest: ReleaseSafetyManifest
) -> list[str]:
    errors: list[str] = []
    item = source.tree.get(manifest.contract_test_path)
    if item is None or item.get("type") != "blob" or item.get("mode") != "100755":
        errors.append(
            f"[RELEASE_MANIFEST] 项目发布安全契约入口不存在或不可执行：{manifest.contract_test_path}"
        )
    primary = [
        (document, job)
        for document in source.workflows.values()
        for job in jobs_map(document).values()
        if job.get("name") == "PR container validation"
    ]
    if len(primary) != 1:
        errors.append(
            "[RELEASE_MANIFEST] PR container validation required job 必须在 active workflow 中唯一"
        )
        return errors
    document, job = primary[0]
    if (
        "if" in job
        or "needs" in job
        or not strict_continue_on_error_disabled(job)
        or has_unsafe_run_defaults(document.data)
        or has_unsafe_run_defaults(job)
    ):
        errors.append(
            f"[RELEASE_MANIFEST] {document.path}: PR required job 必须独立无条件执行且不得改变运行位置"
        )
    step, step_errors = step_reference(
        job, manifest.contract_test_step, "contract_test.pr_step"
    )
    errors.extend(step_errors)
    if step is not None and (
        "if" in step
        or "continue-on-error" in step
        or "shell" in step
        or "working-directory" in step
        or step.get("run") != manifest.contract_test_path
    ):
        errors.append(
            f"[RELEASE_MANIFEST] {document.path}: PR 必须无条件执行声明的项目发布安全契约测试"
        )
    return errors


def release_input_errors(document: ParsedYaml) -> list[str]:
    dispatch = event_map(document).get("workflow_dispatch")
    inputs = dispatch.get("inputs") if isinstance(dispatch, dict) else None
    expected_inputs = {"rollback_sha", "rollback_reason"}
    if not isinstance(inputs, dict) or set(inputs) != expected_inputs:
        return [
            f"[ROLLBACK_TARGET] {document.path}: workflow_dispatch 必须精确声明 rollback_sha 与 rollback_reason"
        ]
    if any(
        not isinstance(inputs[name], dict)
        or inputs[name].get("required", "false") != "false"
        or inputs[name].get("default", "") != ""
        or inputs[name].get("type") != "string"
        for name in expected_inputs
    ):
        return [
            f"[ROLLBACK_TARGET] {document.path}: 回滚输入必须是默认空值的可选 string"
        ]
    return []


def inspect_release_steps(
    document: ParsedYaml,
    manifest: ReleaseSafetyManifest,
    role_jobs: dict[str, dict[str, Any] | None],
    rollback_signal: str | None,
    *,
    dispatch_signal: bool,
) -> list[str]:
    errors: list[str] = []
    prepare = role_jobs["prepare"]
    deploy = role_jobs["deploy"]
    assert isinstance(deploy, dict)
    target_job = prepare if manifest.target_job == "prepare" else deploy
    assert isinstance(target_job, dict)

    scalar_roles = (
        "target",
        "capture",
        "candidate",
        "rollback",
        "cleanup",
    )
    resolved: dict[str, dict[str, Any]] = {}
    for role in scalar_roles:
        job = target_job if role == "target" else deploy
        step_id = manifest.steps[role]
        assert isinstance(step_id, str)
        step, step_errors = step_reference(job, step_id, f"steps.{role}")
        errors.extend(step_errors)
        if step is not None:
            resolved[role] = step

    for role in ("migrations", "verify"):
        step_ids_for_role = manifest.steps[role]
        assert isinstance(step_ids_for_role, list)
        for step_id in step_ids_for_role:
            step, step_errors = step_reference(deploy, step_id, f"steps.{role}")
            errors.extend(step_errors)
            if step is not None:
                resolved[step_id] = step

    failure_id = manifest.steps["failure"]
    if isinstance(failure_id, str):
        step, step_errors = step_reference(deploy, failure_id, "steps.failure")
        errors.extend(step_errors)
        if step is not None:
            resolved["failure"] = step

    if errors:
        return errors

    verify_ids = manifest.steps["verify"]
    assert isinstance(verify_ids, list)
    migration_ids = manifest.steps["migrations"]
    assert isinstance(migration_ids, list)
    expected_migration_guard = manifest.conditions["migration"]
    for step_id in migration_ids:
        assert isinstance(expected_migration_guard, str)
        if (
            normalized_condition(resolved[step_id].get("if"))
            != expected_migration_guard
            or rollback_signal is None
            or not rollback_negative_condition_safe(
                expected_migration_guard,
                rollback_signal,
                dispatch=dispatch_signal,
            )
        ):
            errors.append(
                f"[ROLLBACK_GUARD] {document.path}: migration {step_id} 未在 rollback 模式跳过"
            )

    capture_id = manifest.steps["capture"]
    candidate_id = manifest.steps["candidate"]
    rollback_id = manifest.steps["rollback"]
    cleanup_id = manifest.steps["cleanup"]
    assert isinstance(capture_id, str)
    assert isinstance(candidate_id, str)
    assert isinstance(rollback_id, str)
    assert isinstance(cleanup_id, str)
    ordered_ids = [
        capture_id,
        *migration_ids,
        candidate_id,
        *verify_ids,
        rollback_id,
        cleanup_id,
    ]
    if isinstance(failure_id, str):
        ordered_ids.append(failure_id)
    positions = [step_position(deploy, step_id) for step_id in ordered_ids]
    if any(position < 0 for position in positions) or positions != sorted(positions):
        errors.append(
            f"[ROLLBACK_CAPTURE] {document.path}: manifest 发布安全步骤顺序无效"
        )

    rollback = resolved["rollback"]
    expected_rollback_guard = manifest.conditions["rollback"]
    assert isinstance(expected_rollback_guard, str)
    if normalized_condition(rollback.get("if")) != expected_rollback_guard:
        errors.append(
            f"[ROLLBACK_GUARD] {document.path}: rollback guard 未精确引用 manifest capture/candidate"
        )
    if not rollback_condition_safe(expected_rollback_guard, capture_id, candidate_id):
        errors.append(
            f"[ROLLBACK_GUARD] {document.path}: manifest rollback condition 不是允许的 failure/capture/candidate 合取式"
        )
    if not continue_on_error_disabled(rollback):
        errors.append(
            f"[RELEASE_FAILURE_STATE] {document.path}: rollback 失败不得被隐藏"
        )
    cleanup_condition = manifest.conditions["cleanup"]
    if (
        normalized_condition(resolved["cleanup"].get("if")) != cleanup_condition
        or cleanup_condition != "success()"
    ):
        errors.append(
            f"[RELEASE_FAILURE_STATE] {document.path}: cleanup 只能在成功验收后执行"
        )
    if isinstance(failure_id, str):
        failure_condition = manifest.conditions["failure"]
        if (
            normalized_condition(resolved["failure"].get("if")) != failure_condition
            or failure_condition != "failure()"
            or not continue_on_error_disabled(resolved["failure"])
        ):
            errors.append(
                f"[RELEASE_FAILURE_STATE] {document.path}: failure step guard 必须是 failure()"
            )
    return errors


def inspect_finalize(
    document: ParsedYaml,
    manifest: ReleaseSafetyManifest,
    role_jobs: dict[str, dict[str, Any] | None],
) -> list[str]:
    finalize_id = manifest.jobs["finalize"]
    if finalize_id is None:
        return []
    finalize = role_jobs["finalize"]
    assert isinstance(finalize, dict)
    expected_needs = {manifest.jobs[role] for role in manifest.needs["finalize"]}
    assert all(isinstance(value, str) for value in expected_needs)
    errors: list[str] = []
    finalize_environment = environment_name(finalize)
    finalize_condition = manifest.conditions["finalize"] or ""
    finalize_atoms = flatten_conjunction(finalize_condition)
    finalize_always_atoms = (
        [atom for atom in finalize_atoms if is_function_atom(atom, "always")]
        if finalize_atoms is not None
        else []
    )
    finalize_master_atoms = (
        [atom for atom in finalize_atoms if is_master_guard_atom(atom)]
        if finalize_atoms is not None
        else []
    )
    if (
        normalized_condition(finalize.get("if")) != finalize_condition
        or needs_ids(finalize) != expected_needs
        or contains_secret_context(finalize)
        or value_has_deploy_capability(finalize)
        or (finalize_environment is not None and not deployment_false(finalize))
        or finalize_atoms is None
        or len(finalize_atoms) != 2
        or len(finalize_always_atoms) != 1
        or len(finalize_master_atoms) != 1
    ):
        errors.append(
            f"[RELEASE_FAILURE_STATE] {document.path}: finalize job 未安全依赖发布结果"
        )

    finalize_step_id = manifest.steps["finalize"]
    failure_step_id = manifest.steps["finalize_failure"]
    resolved: dict[str, dict[str, Any]] = {}
    for role, step_id in (
        ("finalize", finalize_step_id),
        ("finalize_failure", failure_step_id),
    ):
        if not isinstance(step_id, str):
            continue
        step, step_errors = step_reference(finalize, step_id, f"steps.{role}")
        errors.extend(step_errors)
        if step is not None:
            resolved[role] = step
    if isinstance(failure_step_id, str) and "finalize_failure" in resolved:
        failure_guard = manifest.conditions["finalize_failure"]
        if normalized_condition(
            resolved["finalize_failure"].get("if")
        ) != failure_guard or not continue_on_error_disabled(
            resolved["finalize_failure"]
        ):
            errors.append(
                f"[RELEASE_FAILURE_STATE] {document.path}: finalize failure guard 无效"
            )
        if isinstance(finalize_step_id, str) and (
            step_position(finalize, finalize_step_id)
            >= step_position(finalize, failure_step_id)
        ):
            errors.append(
                f"[RELEASE_FAILURE_STATE] {document.path}: finalize failure step 顺序无效"
            )
    return errors


def inspect_release(source: RepositorySource) -> tuple[list[str], set[str]]:
    errors: list[str] = []
    if source.release_manifest is None:
        return ["[RELEASE_MANIFEST] 无法读取发布安全适配 manifest"], set()
    try:
        manifest = parse_release_safety_manifest(source.release_manifest)
    except AuditError as error:
        return [f"[RELEASE_MANIFEST] {error}"], set()
    document = source.workflows.get(manifest.workflow_path)
    if document is None:
        return [
            f"[RELEASE_MANIFEST] manifest workflow 不是 active workflow：{manifest.workflow_path}"
        ], set()
    errors.extend(inspect_contract_test(source, manifest))

    for other in source.workflows.values():
        if other.path == document.path:
            continue
        signals = release_capability_signals(source, other)
        if signals:
            errors.append(
                f"[RELEASE_WORKFLOW] {other.path}: 发布能力只能存在于唯一受控 release workflow，检测到 "
                + ", ".join(sorted(signals))
            )

    events = event_map(document)
    if (
        not exact_master_push(events)
        or not set(events).issubset({"push", "workflow_dispatch"})
        or "workflow_dispatch" not in events
    ):
        errors.append(
            f"[RELEASE_EVENT] {document.path}: 发布事件必须精确包含 master push 与 workflow_dispatch"
        )
    errors.extend(release_input_errors(document))
    concurrency = document.data.get("concurrency")
    if (
        not isinstance(concurrency, dict)
        or set(concurrency) != {"group", "cancel-in-progress"}
        or not isinstance(concurrency.get("group"), str)
        or not concurrency["group"].strip()
        or not concurrency_group_safe(concurrency["group"])
        or concurrency.get("cancel-in-progress") != "false"
    ):
        errors.append(
            f"[RELEASE_CONCURRENCY] {document.path}: 发布与回滚必须共享非空串行 concurrency"
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
    role_jobs: dict[str, dict[str, Any] | None] = {}
    for role, job_id in manifest.jobs.items():
        if job_id is None:
            role_jobs[role] = None
            continue
        job = jobs.get(job_id)
        if not isinstance(job, dict):
            errors.append(f"[RELEASE_MANIFEST] jobs.{role} 引用不存在的 job：{job_id}")
            role_jobs[role] = None
        else:
            role_jobs[role] = job

    referenced: set[str] = set()
    for job_id, job in jobs.items():
        if not continue_on_error_disabled(job):
            errors.append(
                f"[RELEASE_FAILURE_STATE] {document.path}: job {job_id} 不得隐藏失败状态"
            )
        if "permissions" in job and not release_job_permissions_safe(
            job["permissions"]
        ):
            errors.append(
                f"[RELEASE_PERMISSION] {document.path}: job {job_id} 权限超出 contents:read"
            )
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

    publish_id = manifest.jobs["publish"]
    deploy_id = manifest.jobs["deploy"]
    prepare_id = manifest.jobs["prepare"]
    finalize_id = manifest.jobs["finalize"]
    assert isinstance(publish_id, str)
    assert isinstance(deploy_id, str)
    publish = role_jobs["publish"]
    deploy = role_jobs["deploy"]
    if any(
        job_id is not None and not isinstance(role_jobs[role], dict)
        for role, job_id in manifest.jobs.items()
    ):
        return errors, referenced
    assert isinstance(publish, dict)
    assert isinstance(deploy, dict)

    declared_job_ids = {
        job_id for job_id in manifest.jobs.values() if isinstance(job_id, str)
    }
    for job_id, job in jobs.items():
        if job_id in declared_job_ids:
            continue
        signals = release_job_capability_signals(source, document, job)
        if signals:
            errors.append(
                f"[RELEASE_MANIFEST] {document.path}: 未声明 job {job_id} 含特权能力："
                + ", ".join(sorted(signals))
            )

    allowed_dev_jobs = {publish_id, deploy_id}
    if isinstance(finalize_id, str):
        allowed_dev_jobs.add(finalize_id)
    unexpected_dev = {
        job_id
        for job_id, job in jobs.items()
        if environment_name(job) == "dev" and job_id not in allowed_dev_jobs
    }
    if unexpected_dev:
        errors.append(
            f"[RELEASE_MANIFEST] {document.path}: 未声明的 dev job："
            + ", ".join(sorted(unexpected_dev))
        )
    if environment_name(publish) != "dev" or not deployment_false(publish):
        errors.append(
            f"[PUBLISH_ENVIRONMENT] {document.path}: manifest publish 必须绑定 dev/deployment:false"
        )
    if environment_name(deploy) != "dev" or deployment_false(deploy):
        errors.append(
            f"[DEPLOY_ENVIRONMENT] {document.path}: manifest deploy 必须绑定真实 dev deployment"
        )

    if isinstance(prepare_id, str):
        prepare = role_jobs["prepare"]
        if not isinstance(prepare, dict):
            return errors, referenced
        expected_prepare_guard = manifest.conditions["prepare"] or ""
        if (
            normalized_condition(prepare.get("if")) != expected_prepare_guard
            or "environment" in prepare
            or prepare.get("runs-on") != "ubuntu-latest"
            or contains_secret_context(prepare)
            or value_has_deploy_capability(prepare)
        ):
            errors.append(
                f"[RELEASE_EVENT] {document.path}: prepare 必须是 manifest 声明的 GitHub-hosted 纯校验 job"
            )
    expected_publish_needs = {manifest.jobs[role] for role in manifest.needs["publish"]}
    expected_deploy_needs = {manifest.jobs[role] for role in manifest.needs["deploy"]}
    assert all(isinstance(value, str) for value in expected_publish_needs)
    assert all(isinstance(value, str) for value in expected_deploy_needs)
    expected_publish_guard = manifest.conditions["publish"]
    expected_deploy_guard = manifest.conditions["deploy"]
    assert isinstance(expected_publish_guard, str)
    assert isinstance(expected_deploy_guard, str)
    dispatch_signal = prepare_id is None
    if isinstance(prepare_id, str):
        prepare = role_jobs["prepare"]
        assert isinstance(prepare, dict)
        outputs = prepare.get("outputs")
        rollback_signals = (
            {
                f"needs.{prepare_id}.outputs.{output_id}"
                for output_id in outputs
                if isinstance(output_id, str)
                and SEMANTIC_ID_PATTERN.fullmatch(output_id)
            }
            if isinstance(outputs, dict)
            else set()
        )
    else:
        rollback_signals = {"github.event.inputs.rollback_sha"}
    rollback_signal = publish_rollback_signal(
        expected_publish_guard,
        rollback_signals,
        dispatch=dispatch_signal,
    )
    if (
        needs_ids(publish) != expected_publish_needs
        or normalized_condition(publish.get("if")) != expected_publish_guard
        or rollback_signal is None
    ):
        errors.append(
            f"[ROLLBACK_GUARD] {document.path}: publish rollback guard/needs 无效"
        )
    if (
        needs_ids(deploy) != expected_deploy_needs
        or normalized_condition(deploy.get("if")) != expected_deploy_guard
        or not any(
            is_function_atom(atom, "always")
            for atom in top_level_conjuncts(expected_deploy_guard)
        )
        or not any(
            is_master_guard_atom(atom)
            for atom in top_level_conjuncts(expected_deploy_guard)
        )
        or rollback_signal is None
        or not deploy_has_explicit_paths(
            expected_deploy_guard,
            publish_id,
            rollback_signal,
            dispatch=dispatch_signal,
            prepare_job_id=prepare_id,
        )
    ):
        errors.append(
            f"[ROLLBACK_GUARD] {document.path}: deploy rollback guard/needs 无效"
        )

    errors.extend(
        inspect_release_steps(
            document,
            manifest,
            role_jobs,
            rollback_signal,
            dispatch_signal=dispatch_signal,
        )
    )
    errors.extend(inspect_finalize(document, manifest, role_jobs))
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
        errors.extend(inspect_code_review_rules(source))
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
