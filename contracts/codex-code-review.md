# 官方 Codex Code Review 治理契约

本文定义跨项目采用官方 Codex Code Review 的共同 MUST。目标是稳定接入和唤醒官方能力，不自建 Reviewer、模型调用服务或平行评论协议。

## 1. 官方能力优先

- MUST：PR 的 AI 审查只采用官方 Codex Code Review；不得创建替代它的 GitHub Action、Bot、Webhook 服务、self-hosted runner 任务或自托管模型调用。
- MUST：官方能力新增或调整后优先更新配置与规则；只有经过单独决策确认的长期关键缺口，才可以设计可关闭、可删除的薄补充层。
- MUST：官方 Review 与项目 CI、分支保护、部署 smoke 和人工业务决策并行存在，不替代其中任何一层。

## 2. 触发与规则分离

- MUST：在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`，由官方集成自动触发新 PR 审查。
- MUST：自动审查未触发或需要重新审查时，使用官方评论命令 `@codex review` 作为人工兜底。
- MUST：每个仓库根目录维护普通文件 `AGENTS.md`，并包含独占一行的精确标题 `## Code Review Rules`。
- MUST：`AGENTS.md` 只声明官方 Reviewer 的审查重点，不能被描述为 Automatic reviews 的开启方式或触发证据。
- 项目扩展点：项目可以在根规则或更近目录的 `AGENTS.md` 中补充架构、协议、数据和真实验收约束，但不得降低根级公共审查原则。

## 3. 审查内容

- MUST：规则优先要求寻找有可触发场景和实际影响的问题，包括但不限于正确性、性能、回归、安全、隐私、权限、可维护性、数据/API 兼容、跨仓协议与 CI/CD 基线风险。
- MUST：PR 描述、实现者解释和已有测试都视为待验证声明；审查应对照改动、相关调用方和测试证据独立判断。
- MUST：避免重复 lint、格式化和类型检查已能稳定发现的问题，避免纯风格偏好、无实际影响的猜测和与当前风险无关的大范围重构建议。
- MUST：不要求官方 Reviewer 使用自定义严重级别、批准口令或评论格式，以免把基线绑定到官方当前输出实现。
- 项目扩展点：各项目补充高风险模块、跨仓消费者、迁移兼容、前端状态协议和真实用户路径。

## 4. v1 合并边界

- MUST：v1 采用观察模式，官方 Review 不新增为 required status check，也不改变现有 `master` branch protection。
- MUST：没有官方稳定状态接口和真实仓库验证前，不假设 Review 能映射为 GitHub required check、approval 或固定 check 名称。
- MUST：Review 发现的问题按现有 PR 对话处理；是否阻塞合并由现有门禁和维护者判断，不增加平行状态机。
- MUST：[GitHub 官方文档](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)只保证无写权限者向已开启 Auto-merge 的 PR 推送时自动关闭；有写权限者推送新提交后不保证自动关闭，Auto-merge 可能继续保持开启。官方 Review 当前又不是 required check，因此 v1 暂不允许仓库或单个 PR 开启 Auto-merge。
- MUST：v1 只启用合并后自动删除远端功能分支；不创建自研合并 Bot、Action、HEAD 监听器或平行状态机来补 GitHub/Codex 当前能力缺口。
- MUST：人工合并前必须确认官方 Review 当前 HEAD、全部 review thread 已解决、required checks 成功，且依赖或发布风险已分类。
- MUST：PR 出现新提交后，旧 Review 不再作为当前 HEAD 的证据；必须重新 Review 并再次确认全部 review thread 已解决，才能人工合并。
- MUST：Dependabot PR 不因 CI 通过而自动合并；运行时依赖、跨大版本升级、构建工具行为变化及会随合并触发生产发布的仓库，都必须先完成兼容性与发布授权判断。
- 项目扩展点：未来只有在官方 Review 能成为与当前 HEAD 绑定的 required gate，或 GitHub 保证任意新提交都会撤销 Auto-merge 后，才重新评估启用原生 Auto-merge。

## 5. 审计与验收

- MUST：中央只读审计检查根 `AGENTS.md` 是 Git tree 中的普通文件，并在 fenced code、HTML comment 与 raw HTML block 之外包含精确 `## Code Review Rules` 标题；缺失、symlink、非普通文件或缺少真实标题统一报告 `[CODE_REVIEW_RULES]`。
- MUST：审计使用固定 `markdown-it-py==3.0.0` 的 CommonMark parser，只接受真实 `h2` token，且 token 对应源码行必须精确等于 `## Code Review Rules`；不得维护平行的手写 Markdown 状态机。
- MUST：直接依赖 `markdown-it-py==3.0.0` 与传递依赖 `mdurl==0.1.2` 在本地入口和两条基线 workflow 中显式校验或固定安装，不得依赖运行环境碰巧预装的版本。
- MUST：中央审计不抓取 GitHub/Codex 页面、不调用私有接口，也不声称验证 Automatic reviews 设置或模型审查质量。
- MUST：中央审计验证纳管产品仓库关闭 Auto-merge 且合并后自动删除远端功能分支；人工合并前是否完成当前 HEAD Review、解决 thread 与风险分类，由真实 PR 验收，不伪装成静态仓库审计结论。
- MUST：官方设置通过真实 PR 验收：Automatic reviews 能产生审查；必要时 `@codex review` 能触发人工兜底；Reviewer 能遵循仓库规则。
- MUST：接入不得新增 review 专用 secret、GitHub App、workflow、runner 或发布权限。
- 项目扩展点：保存测试 PR、Review 链接和观察期结论的方式。
