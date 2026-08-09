# AGENTS.md — engineering-baseline

本仓库维护 Fusion、Audio 与后续项目共同使用的工程治理契约。项目实现细节不得被误升格为公共 MUST。

## 语言与提交

- 所有回复、代码注释和 Git 提交信息使用中文。
- Git 提交标题使用 `<type>: <中文描述>`；正文说明背景、改动和验证，并包含 `Co-Authored-By: Codex <noreply@anthropic.com>`。

## 开发与验证

- 非平凡变更在独立 worktree 和分支中完成；调查默认只读，未经明确授权不得提交、push 或修改远端设置。
- 公共规则变更先补失败 fixture 取得 RED，再做最小实现取得 GREEN。
- 审计器保持只读和 fail-closed，只读取仓库配置、内容及 secret 名称元数据，不读取或输出 secret 值。
- 修改审计能力时同步契约、模板、README、维护手册及正反 fixture，并运行完整基线测试、ruff、shellcheck、YAML 解析和 diff check。
- 官方能力优先；基线只负责接入、规则和可验证治理，不重复实现上游产品能力。

## Code Review Rules

- 优先识别会造成错误放行、错误阻断、权限扩大、secret 暴露、供应链漂移或发布/回滚证据失真的具体问题，并核对新增公共 MUST 是否确实跨项目通用。
- 审计器变更必须同时具有能复现旧缺口的失败 fixture 和保持合法项目通过的正例；只增加字符串匹配而不能证明约束时应指出误报或漏报路径。
- 修改 Action 或公共规则时，核对模板、审计器已知映射、契约和 fixture 是否同步；不重复报告 lint、格式化或纯风格问题，不要求与当前风险无关的重构。只有官方 Review 当前 HEAD、全部 review thread 已解决后，才允许对单个 PR 开启 Auto-merge。
