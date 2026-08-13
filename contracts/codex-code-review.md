# 官方 Codex Code Review 治理契约

本文定义跨项目采用官方 Codex Code Review 的共同 MUST。目标是稳定接入和唤醒官方能力，不自建 Reviewer、模型调用服务或平行评论协议。

## 1. 官方能力优先

- MUST：PR 的 AI 审查只采用官方 Codex Code Review；不得创建替代它的 GitHub Action、Bot、Webhook 服务、self-hosted runner 任务或自托管模型调用。
- MUST：官方能力新增或调整后优先更新配置与规则；只有经过单独决策确认的长期关键缺口，才可以设计可关闭、可删除的薄补充层。
- MUST：官方 Review 与项目 CI、分支保护、部署 smoke 和人工业务决策并行存在，不替代其中任何一层。

## 2. 触发与规则分离

- MUST：在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`，由官方集成自动触发新 PR 审查。
- MUST：把 PR 标记为 Ready 后先等待 Automatic Review；没有明确失败时至少等待 15 分钟，并在发送评论前立即复查 PR 时间线，仍无 Review 结果或在途信号时，才使用官方评论命令 `@codex review` 作为人工兜底。
- MUST：同一 HEAD 不得同时存在多个请求，也不得向已经获得有效结果的 HEAD 重复请求；Review 正在运行时不得再次触发。请求明确失败，或超过至少 15 分钟的预定超时且仍没有结果或在途信号时，允许重试一次并记录原因；重试仍失败则停止审查循环并排查集成，不得制造空提交改变 HEAD。
- MUST：不得为了 emoji、reaction、批准口令或重复确认，向已经获得明确文字结论的 HEAD 再次请求。
- MUST：每个仓库根目录维护普通文件 `AGENTS.md`，并包含独占一行的精确标题 `## Code Review Rules`。
- MUST：`AGENTS.md` 只声明官方 Reviewer 的审查重点，不能被描述为 Automatic reviews 的开启方式或触发证据。
- 项目扩展点：项目可以在根规则或更近目录的 `AGENTS.md` 中补充架构、协议、数据和真实验收约束，但不得降低根级公共审查原则。

## 3. 审查内容

- MUST：规则优先要求寻找有可触发场景和实际影响的问题，包括但不限于正确性、性能、回归、安全、隐私、权限、可维护性、数据/API 兼容、跨仓协议与 CI/CD 基线风险。
- MUST：PR 描述、实现者解释和已有测试都视为待验证声明；审查应对照改动、相关调用方和测试证据独立判断。
- MUST：避免重复 lint、格式化和类型检查已能稳定发现的问题，避免纯风格偏好、无实际影响的猜测和与当前风险无关的大范围重构建议。
- MUST：不要求官方 Reviewer 使用自定义严重级别、批准口令或评论格式，以免把基线绑定到官方当前输出实现。
- 项目扩展点：各项目补充高风险模块、跨仓消费者、迁移兼容、前端状态协议和真实用户路径。

## 4. 收敛式 Review

本节用于防止 review churn：官方 Review 是稳定变更的独立风险关卡，不是持续开发阶段的穷举式调试循环。

“稳定 HEAD”指当前范围已冻结、没有已知待提交代码、项目测试和 required CI 已通过，且跨仓共享协议已经对齐；只有该状态才进入初审或最终复审。

### 4.1 Draft 与范围冻结

- MUST：非平凡 PR 先保持 Draft，在实现、项目测试、CI 契约和内部交叉审查完成后冻结范围，再进入官方 Review；不得把官方 Review 当作逐提交调试器。
- MUST：包含多个可独立验证的架构边界时拆分为阶段 PR，例如数据/API、后台任务/索引和部署验收；跨仓变更先冻结共享协议，再分别进入最终 Review。
- MUST：阶段 PR 说明其依赖与验收边界；只有真正完成 Issue 整体交付的最终集成 PR 使用 `Closes #xx`，避免阶段合并提前关闭需求。
- 项目扩展点：项目可以按风险定义大型 PR 提醒阈值，但文件数或代码行数只能作为拆分信号，不能替代架构边界判断。

### 4.2 一轮收齐与批量修复

- MUST：等待一轮 Review 完整结束并收齐 findings，再统一分类和修复；不得一条 finding 对应一次 push 和一次完整 Review。
- MUST：对当前范围内可复现且有实际影响的问题完成修复；重复、outdated、既有问题、明确非目标或未支持的极端场景，允许说明依据后解决 thread、拒绝或转为后续 Issue，不因建议有效就自动扩大当前 PR 范围。
- MUST：按根因合并相关修复，先在本地完成针对性回归和内部复核，再把一个完整修复批次推到 PR；required CI 仍按仓库规则运行，但不得为了启动下一轮 Review 拆出无意义的中间 push。

### 4.3 Single-flight、预算与停止条件

- MUST：同一 HEAD 同一时刻只能有一个 Review 请求；Review 正在运行或结果尚未返回时不得排队新的请求。运行期间出现新提交时，先等待当前结果、完成剩余批量修复，再对最终稳定 HEAD 请求一次复审；明确失败或预定超时且没有任何结果的尝试不计为完整 Review 轮次，并按前述边界允许重试一次。
- MUST：普通 PR 最多两轮完整官方 Review，即初审和一次最终复审；第三轮必须由维护者显式记录原因，并先判断是否需要拆分 PR、收窄范围或接受有依据的非阻塞项，不得自动进入下一轮。
- MUST：官方 Reviewer 对当前 HEAD 给出未发现重大问题的明确文字结论，即视为本轮 Review 通过；不要求 emoji、reaction、固定措辞或额外重复确认。
- MUST：人工合并仍要求 Review 当前 HEAD；新提交会使旧 Review 失去最终 HEAD 证据资格，但不要求每个中间提交都立即重新 Review，只在实现与修复重新稳定后触发一次。

## 5. v1 合并边界

- MUST：v1 采用观察模式，官方 Review 不新增为 required status check，也不改变现有 `master` branch protection。
- MUST：没有官方稳定状态接口和真实仓库验证前，不假设 Review 能映射为 GitHub required check、approval 或固定 check 名称。
- MUST：Review 发现的问题按现有 PR 对话处理；是否阻塞合并由现有门禁和维护者判断，不增加平行状态机。
- MUST：[GitHub 官方文档](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)只保证无写权限者向已开启 Auto-merge 的 PR 推送时自动关闭；有写权限者推送新提交后不保证自动关闭，Auto-merge 可能继续保持开启。官方 Review 当前又不是 required check，因此 v1 暂不允许仓库或单个 PR 开启 Auto-merge。
- MUST：不创建自研合并 Bot、Action、HEAD 监听器或平行状态机来补 GitHub/Codex 当前能力缺口。
- MUST：合并后自动删除远端分支不是所有项目的公共强制项。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才允许启用该设置；否则必须关闭，避免 GitHub 删除仍需复用的长期分支。
- MUST：人工合并前必须确认官方 Review 当前 HEAD、全部 review thread 已解决、required checks 成功，且依赖或发布风险已分类。
- MUST：PR 在最终 Review 后出现新提交时，旧 Review 不再作为当前 HEAD 的合并证据；先完成全部修改并恢复稳定 HEAD，再按收敛式 Review 预算完成最终复审和 thread 确认。
- MUST：Dependabot PR 不因 CI 通过而自动合并；运行时依赖、跨大版本升级、构建工具行为变化及会随合并触发生产发布的仓库，都必须先完成兼容性与发布授权判断。
- 项目扩展点：未来只有在官方 Review 能成为与当前 HEAD 绑定的 required gate，或 GitHub 保证任意新提交都会撤销 Auto-merge 后，才重新评估启用原生 Auto-merge。

## 6. 审计与验收

- MUST：中央只读审计检查根 `AGENTS.md` 是 Git tree 中的普通文件，并在 fenced code、HTML comment 与 raw HTML block 之外包含精确 `## Code Review Rules` 标题；缺失、symlink、非普通文件或缺少真实标题统一报告 `[CODE_REVIEW_RULES]`。
- MUST：审计使用固定 `markdown-it-py==3.0.0` 的 CommonMark parser，只接受真实 `h2` token，且 token 对应源码行必须精确等于 `## Code Review Rules`；不得维护平行的手写 Markdown 状态机。
- MUST：直接依赖 `markdown-it-py==3.0.0` 与传递依赖 `mdurl==0.1.2` 在本地入口和两条基线 workflow 中显式校验或固定安装，不得依赖运行环境碰巧预装的版本。
- MUST：中央审计不抓取 GitHub/Codex 页面、不调用私有接口，也不声称验证 Automatic reviews 设置、模型审查质量、同一 HEAD 请求次数、在途 Review 或审查轮次预算；这些运行态事实由真实 PR 时间线验收。
- MUST：中央审计验证纳管产品仓库关闭 Auto-merge；分支自动删除取决于项目真实分支模型，不由公共审计强制。人工合并前是否完成当前 HEAD Review、解决 thread 与风险分类，由真实 PR 验收，不伪装成静态仓库审计结论。
- MUST：官方设置通过真实 PR 验收：Automatic reviews 能产生审查；必要时 `@codex review` 能触发人工兜底；Reviewer 能遵循仓库规则。
- MUST：接入不得新增 review 专用 secret、GitHub App、workflow、runner 或发布权限。
- 项目扩展点：保存测试 PR、Review 链接和观察期结论的方式。
