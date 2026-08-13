# 官方 Codex Code Review 治理契约

本文定义跨项目采用官方 Codex Code Review 的共同 MUST。目标是稳定接入和唤醒官方能力，不自建 Reviewer、模型调用服务或平行评论协议。

## 1. 官方能力优先

- MUST：PR 的 AI 审查只采用官方 Codex Code Review；不得创建替代它的 GitHub Action、Bot、Webhook 服务、self-hosted runner 任务或自托管模型调用。
- MUST：官方能力新增或调整后优先更新配置与规则；只有经过单独决策确认的长期关键缺口，才可以设计可关闭、可删除的薄补充层。
- MUST：官方 Review 与项目 CI、分支保护、部署 smoke 和人工业务决策并行存在，不替代其中任何一层。

## 2. 触发与规则分离

- MUST：在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`，由官方集成自动触发新 PR 审查。
- MUST：Automatic Review 未出现时，先按官方排障说明检查仓库开关、Codex cloud 配置、触发事件与 PR 时间线；确认没有结果或在途信号后，才使用官方评论命令 `@codex review` 人工兜底，不用空提交制造触发。
- MUST：同一 HEAD 不得并发或重复请求；Review 正在运行，或已经产生有效结果时，不得再次触发，也不得为了 emoji、reaction、批准口令或重复确认追加请求。
- MUST：每个仓库根目录维护普通文件 `AGENTS.md`，并包含独占一行的精确标题 `## Code Review Rules`。
- MUST：`AGENTS.md` 只声明官方 Reviewer 的高后果审查重点，不能被描述为 Automatic reviews 的开启方式、触发证据或 required check。
- 项目扩展点：项目可以在根规则或更近目录的 `AGENTS.md` 中补充架构、协议、数据和真实验收约束，但不得降低根级公共审查原则。

## 3. 审查内容

- MUST：遵循[官方 Code Review 定位](https://learn.chatgpt.com/docs/third-party/github)：标准 GitHub Review 只提交高优先级 P0/P1；规则只保留两到三条简洁、项目特有且结果导向的约束，并给出安全路径或正反 few-shot。
- MUST：finding 只有同时满足以下条件才是阻塞项：由当前 PR 引入、存在当前可达的触发路径、违反明确验收标准，并会造成具体的正确性、安全、权限、数据、兼容性或发布后果；标签本身不能替代影响证据。
- MUST：P0/P1 在满足上述证据时默认阻塞。若产品仍输出 P2/P3，则默认不阻塞也不要求修改；只有维护者给出可复现证据并明确升级后，才进入当前 PR 的阻塞集合。
- MUST：纯防御性加固、需要未来维护者同时修改规则与测试才成立的假设、测试还可增加更多 fixture、lint/格式/措辞/命名、纯重构或没有当前影响的建议默认不报告；出现时记录“不阻塞”的处置依据即可，无需重新 Review。
- MUST：PR 描述、实现者解释和已有测试都视为待验证声明；审查应对照改动、相关调用方和测试证据独立判断，但机械一致性继续由确定性 CI 负责。
- 项目扩展点：各项目补充高风险模块、跨仓消费者、迁移兼容、前端状态协议和真实用户路径。

## 4. Finding 处置与收敛

本节用于防止 review churn：官方 Review 是高信号风险探测器，不是穷举式调试器，也不是独立于 CI 和维护者判断的平行状态机。

“稳定变更”指当前范围已冻结、没有已知待提交代码、项目测试已通过，且跨仓共享协议已经对齐；只有该状态才进入官方 Review。

### 4.1 Draft 与范围冻结

- MUST：非平凡 PR 先保持 Draft，在实现、项目测试、CI 契约和内部交叉审查完成后冻结范围，再进入官方 Review；不得把官方 Review 当作逐提交调试器。
- MUST：包含多个可独立验证的架构边界时拆分为阶段 PR，例如数据/API、后台任务/索引和部署验收；跨仓变更先冻结共享协议，再分别进入最终 Review。
- MUST：阶段 PR 说明其依赖与验收边界；只有真正完成 Issue 整体交付的最终集成 PR 使用 `Closes #xx`，避免阶段合并提前关闭需求。
- 项目扩展点：项目可以按风险定义大型 PR 提醒阈值，但文件数或代码行数只能作为拆分信号，不能替代架构边界判断。

### 4.2 一轮收齐与批量修复

- MUST：等待一轮 Review 完整结束并收齐 findings，再按“阻塞、非阻塞、重复/outdated、既有问题或范围外”统一分类；不得一条 finding 对应一次 push 和一次完整 Review。
- MUST：阻塞 finding 按根因批量修复，在本地完成针对性回归后推送一个完整批次；只有修复显著改变原风险面时，才请求一次聚焦该阻塞项的定向 Review。
- MUST：非阻塞 finding 回复影响判断与处置依据后解决 thread；不修改代码、不创建跟踪 Issue，也不触发新 Review，除非维护者另行决定其确有独立价值。
- MUST：Review 后新增与 finding 无关的业务范围时，PR 退回 Draft、重新冻结范围并重新审查；仅修复已分类 finding 时，以修复证据、确定性测试和 required CI 完成闭环。

### 4.3 通过与停止条件

- MUST：官方 Reviewer 给出未发现重大问题的明确文字结论，或所有 finding 均已完成阻塞分类与处置，即视为本轮 Review 闭环；不要求 emoji、reaction、固定措辞或零评论。
- MUST：P2/P3、加固建议和已解释的非阻塞 thread 不得成为继续修改与复审的理由；若定向 Review 又提出新的非阻塞建议，直接记录处置并停止。
- MUST：定向 Review 再发现新的阻塞 P0/P1，说明范围或设计仍不稳定；维护者必须先决定拆分 PR、收窄范围或重新设计，不得自动进入无界循环。

## 5. v1 合并边界

- MUST：v1 采用观察模式，官方 Review 不新增为 required status check，也不改变现有 `master` branch protection。
- MUST：没有官方稳定状态接口和真实仓库验证前，不假设 Review 能映射为 GitHub required check、approval 或固定 check 名称。
- MUST：Review 发现的问题按现有 PR 对话处理；是否阻塞合并由本契约的影响证据、现有门禁和维护者判断，不增加平行状态机。
- MUST：[GitHub 官方文档](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)只保证无写权限者向已开启 Auto-merge 的 PR 推送时自动关闭；有写权限者推送新提交后不保证自动关闭，Auto-merge 可能继续保持开启。官方 Review 当前又不是 required check，因此 v1 暂不允许仓库或单个 PR 开启 Auto-merge。
- MUST：不创建自研合并 Bot、Action、HEAD 监听器或平行状态机来补 GitHub/Codex 当前能力缺口。
- MUST：合并后自动删除远端分支不是所有项目的公共强制项。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才允许启用该设置；否则必须关闭，避免 GitHub 删除仍需复用的长期分支。
- MUST：人工合并前必须确认 required checks 成功、阻塞 finding 已修复或有明确风险接受、全部 review thread 已完成处置，且依赖或发布风险已分类；非阻塞 finding 无需修改代码或重新 Review。
- MUST：Dependabot PR 不因 CI 通过而自动合并；运行时依赖、跨大版本升级、构建工具行为变化及会随合并触发生产发布的仓库，都必须先完成兼容性与发布授权判断。
- 项目扩展点：未来只有在官方 Review 能成为与当前 HEAD 绑定的 required gate，或 GitHub 保证任意新提交都会撤销 Auto-merge 后，才重新评估启用原生 Auto-merge。

## 6. 审计与验收

- MUST：中央只读审计检查根 `AGENTS.md` 是 Git tree 中的普通文件，并在 fenced code、HTML comment 与 raw HTML block 之外包含精确 `## Code Review Rules` 标题；缺失、symlink、非普通文件或缺少真实标题统一报告 `[CODE_REVIEW_RULES]`。
- MUST：审计使用固定 `markdown-it-py==3.0.0` 的 CommonMark parser，只接受真实 `h2` token，且 token 对应源码行必须精确等于 `## Code Review Rules`；不得维护平行的手写 Markdown 状态机。
- MUST：直接依赖 `markdown-it-py==3.0.0` 与传递依赖 `mdurl==0.1.2` 在本地入口和两条基线 workflow 中显式校验或固定安装，不得依赖运行环境碰巧预装的版本。
- MUST：中央审计不抓取 GitHub/Codex 页面、不调用私有接口，也不声称验证 Automatic reviews 设置、模型审查质量、同一 HEAD 请求次数或在途 Review；这些运行态事实由真实 PR 时间线验收。
- MUST：中央审计验证纳管产品仓库关闭 Auto-merge；分支自动删除取决于项目真实分支模型，不由公共审计强制。人工合并前是否完成 finding 分类、thread 处置与风险判断，由真实 PR 验收，不伪装成静态仓库审计结论。
- MUST：官方设置通过真实 PR 验收：Automatic reviews 能产生审查；必要时 `@codex review` 能触发人工兜底；Reviewer 能遵循仓库规则。
- MUST：接入不得新增 review 专用 secret、GitHub App、workflow、runner 或发布权限。
- 项目扩展点：保存测试 PR、Review 链接和观察期结论的方式。
