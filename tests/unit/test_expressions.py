"""表达式解析器与 API 重试的单元测试。

fixture 测试只能间接覆盖这些纯函数：一个解析分支写错，往往表现为某个 fixture
“碰巧仍然失败”，而不是定位到具体函数。这里直接对函数做表驱动断言。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "audit_github_baseline.py"
)
_spec = importlib.util.spec_from_file_location("audit_github_baseline", MODULE_PATH)
assert _spec is not None and _spec.loader is not None
audit = importlib.util.module_from_spec(_spec)
# dataclass 装饰器要求模块在执行期间已经注册到 sys.modules。
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)


class StripOuterParenthesesTest(unittest.TestCase):
    def test_strips_only_true_wrappers(self) -> None:
        cases = {
            "a": "a",
            "(a)": "a",
            "((a))": "a",
            "  ( a ) ": "a",
            # 首个左括号不在末尾闭合，整体不是被包裹的表达式。
            "(a) && (b)": "(a) && (b)",
            "(a) || (b)": "(a) || (b)",
            # 括号出现在字符串字面量里，不参与配对。
            "('(')": "'('",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(audit.strip_outer_parentheses(expression), expected)


class SplitTopLevelTest(unittest.TestCase):
    def test_splits_only_at_depth_zero(self) -> None:
        self.assertEqual(audit.split_top_level("a && b", "&&"), ["a", "b"])
        self.assertEqual(
            audit.split_top_level("a && (b && c)", "&&"), ["a", "(b && c)"]
        )
        self.assertEqual(audit.split_top_level("a || b || c", "||"), ["a", "b", "c"])

    def test_ignores_operator_inside_quotes(self) -> None:
        self.assertEqual(
            audit.split_top_level("a == '&&' && b", "&&"), ["a == '&&'", "b"]
        )

    def test_returns_single_part_when_operator_absent(self) -> None:
        self.assertEqual(audit.split_top_level("a", "&&"), ["a"])
        self.assertEqual(audit.split_top_level("(a)", "&&"), ["a"])


class FlattenConjunctionTest(unittest.TestCase):
    def test_flattens_nested_conjunctions(self) -> None:
        self.assertEqual(audit.flatten_conjunction("a && (b && c)"), ["a", "b", "c"])

    def test_rejects_any_disjunction(self) -> None:
        self.assertIsNone(audit.flatten_conjunction("a || b"))
        self.assertIsNone(audit.flatten_conjunction("a && (b || c)"))


class GuardAtomTest(unittest.TestCase):
    def test_master_guard_atom(self) -> None:
        self.assertTrue(audit.is_master_guard_atom("github.ref == 'refs/heads/master'"))
        self.assertTrue(
            audit.is_master_guard_atom('(github.ref  ==  "refs/heads/master")')
        )
        self.assertFalse(
            audit.is_master_guard_atom("github.ref != 'refs/heads/master'")
        )
        self.assertFalse(
            audit.is_master_guard_atom("github.ref == 'refs/heads/master-hotfix'")
        )

    def test_guard_atom_follows_configured_branch(self) -> None:
        import os

        os.environ[audit.DEFAULT_BRANCH_ENV] = "main"
        try:
            self.assertTrue(
                audit.is_master_guard_atom("github.ref == 'refs/heads/main'")
            )
            self.assertFalse(
                audit.is_master_guard_atom("github.ref == 'refs/heads/master'")
            )
        finally:
            del os.environ[audit.DEFAULT_BRANCH_ENV]

    def test_function_and_dispatch_atoms(self) -> None:
        self.assertTrue(audit.is_function_atom("always()", "always"))
        self.assertTrue(audit.is_function_atom("  failure( ) ", "failure"))
        self.assertFalse(audit.is_function_atom("always(1)", "always"))
        self.assertTrue(
            audit.is_dispatch_atom("github.event_name == 'workflow_dispatch'")
        )
        self.assertTrue(
            audit.is_non_dispatch_atom("github.event_name != 'workflow_dispatch'")
        )
        self.assertTrue(audit.is_non_dispatch_atom("github.event_name == 'push'"))


class RollbackConditionTest(unittest.TestCase):
    ALLOWED = (
        "failure() && steps.capture_previous.outcome == 'success' "
        "&& steps.candidate_deploy.outputs.entered == 'true'"
    )

    def test_accepts_allowed_conjunction(self) -> None:
        self.assertTrue(
            audit.rollback_condition_safe(
                self.ALLOWED, "capture_previous", "candidate_deploy"
            )
        )

    def test_rejects_extra_or_missing_atoms(self) -> None:
        cases = [
            "failure() && steps.capture_previous.outcome == 'success'",
            self.ALLOWED + " && success()",
            self.ALLOWED + " && false",
            "always() && steps.capture_previous.outcome == 'success' "
            "&& steps.candidate_deploy.outputs.entered == 'true'",
        ]
        for condition in cases:
            with self.subTest(condition=condition):
                self.assertFalse(
                    audit.rollback_condition_safe(
                        condition, "capture_previous", "candidate_deploy"
                    )
                )


class ConcurrencyGroupTest(unittest.TestCase):
    def test_accepts_constant_and_allowed_contexts(self) -> None:
        for group in (
            "master-release",
            "${{ github.repository }}",
            "release-${{ github.ref }}",
            "${{ format('{0}-{1}', github.workflow, github.ref_name) }}",
        ):
            with self.subTest(group=group):
                self.assertTrue(audit.concurrency_group_safe(group))

    def test_rejects_partitioning_contexts(self) -> None:
        for group in (
            "${{ github.event_name }}",
            "${{ github.run_id }}",
            "${{ github.event.inputs.rollback_sha }}",
            "${{ format('{0}', github.event_name) }}",
            "${{ format(github.ref, github.ref) }}",
            "${{ unclosed",
        ):
            with self.subTest(group=group):
                self.assertFalse(audit.concurrency_group_safe(group))


class ContinueOnErrorTest(unittest.TestCase):
    def test_step_level_accepts_explicit_false_forms(self) -> None:
        self.assertTrue(audit.continue_on_error_disabled({}))
        self.assertTrue(
            audit.continue_on_error_disabled({"continue-on-error": "false"})
        )
        self.assertTrue(
            audit.continue_on_error_disabled({"continue-on-error": "${{ false }}"})
        )
        self.assertFalse(
            audit.continue_on_error_disabled({"continue-on-error": "true"})
        )

    def test_pr_required_job_variant_is_stricter(self) -> None:
        self.assertTrue(audit.strict_continue_on_error_disabled({}))
        self.assertTrue(
            audit.strict_continue_on_error_disabled({"continue-on-error": "false"})
        )
        # PR required job 必须无条件执行，因此这里连 ${{ false }} 都不接受；
        # release 内其他 job 走 continue_on_error_disabled 的宽松判定。
        self.assertFalse(
            audit.strict_continue_on_error_disabled(
                {"continue-on-error": "${{ false }}"}
            )
        )


class SecretEnumerationTest(unittest.TestCase):
    def test_static_names_are_enumerable(self) -> None:
        value = {"env": {"A": "${{ secrets.TOKEN }}", "B": "${{ secrets['OTHER'] }}"}}
        self.assertTrue(audit.contains_secret_context(value))
        self.assertTrue(audit.secret_context_is_enumerable(value))
        self.assertEqual(audit.referenced_secret_names(value), {"TOKEN", "OTHER"})

    def test_dynamic_lookup_is_not_enumerable(self) -> None:
        value = {"env": {"A": "${{ secrets[format('T_{0}', matrix.name)] }}"}}
        self.assertTrue(audit.contains_secret_context(value))
        self.assertFalse(audit.secret_context_is_enumerable(value))


class HttpStatusTest(unittest.TestCase):
    def test_parses_gh_error_format(self) -> None:
        self.assertEqual(audit.http_status("gh: Not Found (HTTP 404)"), 404)
        self.assertEqual(audit.http_status("gh: Bad Gateway (HTTP 502)"), 502)
        self.assertIsNone(audit.http_status("dial tcp: connection refused"))

    def test_transient_classification(self) -> None:
        self.assertTrue(audit.is_transient(None))
        self.assertTrue(audit.is_transient(503))
        self.assertTrue(audit.is_transient(429))
        self.assertFalse(audit.is_transient(404))
        self.assertFalse(audit.is_transient(403))


class _Result:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class GhApiRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._run = subprocess.run
        self._sleep = audit.time.sleep
        # 退避时长是被断言的行为，必须由测试自己决定，不能继承外部环境变量。
        self._retry_base = audit.os.environ.pop(
            "BASELINE_AUDIT_RETRY_BASE_SECONDS", None
        )
        self.calls: list[list[str]] = []
        self.sleeps: list[float] = []
        audit.time.sleep = lambda seconds: self.sleeps.append(seconds)

    def tearDown(self) -> None:
        subprocess.run = self._run
        audit.time.sleep = self._sleep
        if self._retry_base is not None:
            audit.os.environ["BASELINE_AUDIT_RETRY_BASE_SECONDS"] = self._retry_base

    def _patch(self, results: list[_Result]) -> None:
        queue = list(results)

        def fake_run(command: list[str], **_: object) -> _Result:
            self.calls.append(command)
            return queue.pop(0)

        subprocess.run = fake_run

    def test_retries_transient_then_succeeds(self) -> None:
        self._patch(
            [
                _Result(1, stderr="gh: Bad Gateway (HTTP 502)"),
                _Result(1, stderr="dial tcp: connection refused"),
                _Result(0, stdout='{"ok": true}'),
            ]
        )
        self.assertEqual(audit.gh_api("owner/repo", "x"), {"ok": True})
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.sleeps, [2.0, 4.0])

    def test_does_not_retry_terminal_status(self) -> None:
        self._patch([_Result(1, stderr="gh: Not Found (HTTP 404)")])
        with self.assertRaises(audit.AuditUnavailable):
            audit.gh_api("owner/repo", "x")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_optional_returns_none_only_for_terminal_status(self) -> None:
        self._patch([_Result(1, stderr="gh: Not Found (HTTP 404)")])
        self.assertIsNone(audit.gh_api("owner/repo", "x", optional=True))
        self.assertEqual(len(self.calls), 1)

    def test_optional_persistent_outage_is_unavailable_not_missing(self) -> None:
        # 关键回归：持续 5xx 不得被降级成“配置缺失”，否则会变成假漂移。
        self._patch([_Result(1, stderr="gh: Service Unavailable (HTTP 503)")] * 4)
        with self.assertRaises(audit.AuditUnavailable):
            audit.gh_api("owner/repo", "x", optional=True)
        self.assertEqual(len(self.calls), audit.GH_API_MAX_ATTEMPTS)

    def test_invalid_json_is_unavailable(self) -> None:
        self._patch([_Result(0, stdout="not json")])
        with self.assertRaises(audit.AuditUnavailable):
            audit.gh_api("owner/repo", "x")


class DefaultBranchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.env = audit.os.environ

    def tearDown(self) -> None:
        self.env.pop(audit.DEFAULT_BRANCH_ENV, None)

    def test_defaults_to_master(self) -> None:
        self.env.pop(audit.DEFAULT_BRANCH_ENV, None)
        self.assertEqual(audit.default_branch(), "master")

    def test_honours_override(self) -> None:
        self.env[audit.DEFAULT_BRANCH_ENV] = "main"
        self.assertEqual(audit.default_branch(), "main")

    def test_rejects_injection_shaped_values(self) -> None:
        for value in ("../evil", "a b", "-x", "main?ref=x", "main&x=1"):
            with self.subTest(value=value):
                self.env[audit.DEFAULT_BRANCH_ENV] = value
                with self.assertRaises(audit.AuditError):
                    audit.default_branch()


if __name__ == "__main__":
    unittest.main()
