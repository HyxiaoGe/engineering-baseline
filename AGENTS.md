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
- 修改 Action 或公共规则时，核对模板、审计器已知映射、契约和 fixture 是否同步；不重复报告 lint、格式化或纯风格问题，不要求与当前风险无关的重构。官方 Review 当前不是 required check，且 GitHub 对有写权限者推送新提交不保证自动关闭 Auto-merge；v1 暂不允许对单个 PR 开启 Auto-merge，只在 Review 当前 HEAD、全部 review thread 已解决后人工合并。

## 官方 Review 收敛

- PR 在 Draft 阶段完成实现、测试、内部交叉审查和范围冻结后，再让 Automatic reviews 审查稳定 HEAD；官方 Review 不作为逐提交调试器。
- 一轮 findings 全部返回后按根因批量修复；同一 HEAD 最多人工请求一次，Review 正在运行时不得再次评论 `@codex review`。
- 正常最多两轮完整官方 Review；第三轮必须显式判断拆分、收窄范围或有依据地接受非阻塞项。
- 当前 HEAD 获得未发现重大问题的明确文字结论即视为通过，不追求 emoji、reaction、固定批准口令或重复确认。
- 新提交会让旧 Review 失去最终 HEAD 证据资格，但不要求每个中间提交立即重审；全部修复完成并恢复稳定 HEAD 后只触发一次最终复审。
