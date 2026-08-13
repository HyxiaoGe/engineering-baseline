# GitHub 工程基线

这是 [HyxiaoGe/engineering-baseline](https://github.com/HyxiaoGe/engineering-baseline) 公开仓库维护的一套可复用 GitHub Actions 与仓库治理基线。它统一跨项目的安全边界和验收证据，不统一项目内部的构建方式。

基线仓库自身不会自动修改纳管项目。`scripts/audit-github-baseline.sh` 只通过 GitHub GET API 读取仓库配置、工作流内容以及 secret **名称**，不会读取或输出 secret 值。

当前纳管仓库记录在 `repositories.txt`。公共规则的变更、Action 升级、新项目接入和漂移处理统一从 [MAINTENANCE.md](MAINTENANCE.md) 进入。

## 接入顺序

1. 从独立 Git worktree 创建变更分支，避免污染长期开发目录。
2. 复制 `templates/AGENTS.md` 到项目根目录，替换全部 `PROJECT_REPLACE` 项并补齐项目内部规则，保留精确标题 `## Code Review Rules`。
3. 在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`；规则只决定审查重点，不负责触发，人工兜底使用 `@codex review`。
4. 保持仓库 Auto-merge 关闭；官方 Review 尚非 required check 时不得对单个 PR 开启 Auto-merge。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才启用合并后自动删除远端分支。
5. 复制 `templates/pr-ci.yml`、`templates/release.yml`、`templates/release-safety.yml` 和 `templates/release-safety-contract.sh`；将后两份分别安装为 `.github/release-safety.yml` 与 `.github/scripts/release-safety-contract.sh`，保持 wrapper 为 `100755`，再替换所有 `PROJECT_REPLACE` 项。
6. 在仓库内实现项目自己的 PR 验证、镜像发布、向前迁移、部署、自动恢复、容器内 smoke、成功后镜像清理和发布收尾脚本；由固定 wrapper 调用项目语言或容器内的可执行契约测试，并让 manifest 声明 wrapper 与 PR 稳定步骤 ID。
7. 创建 `dev` Environment，把发布所需 secret 移入该 Environment；确认发布成功后清理 repository-scope secrets。
8. 为 `master` 启用保护规则，要求 GitHub Actions 产生的 `PR container validation`，并保持 strict。
9. 在真实 PR 上先让新检查通过，再原子替换旧 required check；不要先删除旧门禁。
10. 合并后核对运行容器的 image ref、内容 ID 与 `DEPLOY_TARGET_SHA`，并执行容器内部 smoke。
11. 使用只读审计检查规则漂移。

完整 MUST 和项目扩展点见 [CI/CD 公共契约](contracts/ci-cd-baseline.md) 与 [官方 Codex Code Review 治理契约](contracts/codex-code-review.md)。

## 官方 Codex Code Review

基线只接入和治理官方 Codex Code Review，不自建 Reviewer、GitHub Action、Bot、Webhook 服务、模型调用或评论协议。自动唤醒使用官方 `Automatic reviews`；没有自动触发，或批量修复后需要对稳定 HEAD 做最终复审时，才在 PR 评论使用 `@codex review`。

根 `AGENTS.md` 的 `## Code Review Rules` 只告诉官方 Reviewer 应优先检查哪些项目风险，不能开启 Automatic reviews，也不能证明自动审查已经触发。v1 保持观察模式，不增加 required check，不改变现有 branch protection；官方设置通过真实 PR 验收，中央审计只验证仓库内可稳定读取的规则文件。完整边界见 [官方治理契约](contracts/codex-code-review.md)。

采用收敛式 Review：非平凡 PR 在 Draft 阶段完成实现、测试、内部交叉审查与范围冻结，再让官方 Review 检查稳定 HEAD。一轮 findings 完整返回后按根因批量修复；同一 HEAD 不允许并发或对有效结果重复请求，Review 正在运行时不得排队新的请求。普通 PR 最多两轮完整 Review，即初审和最终复审；第三轮必须先由维护者判断拆分、收窄范围或接受有依据的非阻塞项。

官方 Reviewer 对当前 HEAD 给出未发现重大问题的明确文字结论即视为通过，不追求 emoji、reaction 或固定批准口令。新提交会使旧 Review 失去最终 HEAD 证据资格，但不要求每个中间提交立即重审；完成一批修改并恢复稳定 HEAD 后只触发一次最终复审。包含多个独立架构边界的大型需求应拆成阶段 PR，跨仓变更先冻结共享协议，只有最终集成 PR 使用 `Closes #xx`。

PR 转为 Ready 后若 Automatic Review 尚未出现，在没有明确失败时至少等待 15 分钟，并在人工评论前立即复查时间线。请求明确失败，或超过预定超时且没有结果、没有在途信号时允许重试一次并记录原因；重试仍失败就停止 Review 循环并排查官方集成，不通过空提交制造新 HEAD。

## Auto-merge 与分支清理

GitHub 只保证无写权限者推送新提交时关闭 Auto-merge；有写权限者推送后不保证自动关闭。由于官方 Review 当前不是 required check，纳管产品仓库在 v1 暂不允许开启 Auto-merge，也不为单个 PR 启用它。

人工合并前必须确认官方 Review 当前 HEAD、全部 review thread 已解决且 required checks 成功；最终 Review 后出现新提交时，完成修改并恢复稳定 HEAD 后再做一次最终复审，不逐个审查中间提交。Dependabot PR 不会自动合并；尤其是运行时依赖、跨大版本升级、构建行为变化，以及合并即触发生产发布的仓库，仍需兼容性判断和明确发布授权。

分支自动删除不是公共强制项。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才启用 GitHub 的合并后自动删除；存在未保护且需要复用的 `dev`、`release` 等长期 head 分支时必须关闭。本地 worktree 和分支始终只在确认已合并、工作区干净且没有独有提交后清理。

## 只读审计

前置条件：已安装并登录 `gh`，安装 `Python 3`、`PyYAML>=6`、`markdown-it-py==3.0.0` 与 `mdurl==0.1.2`，当前身份对目标仓库至少具有读取 Actions、Environment、branch protection 和 secret 名称元数据的权限。

```bash
./scripts/audit-github-baseline.sh \
  owner/backend \
  owner/frontend
```

审计当前维护清单无需手工重复仓库参数：

```bash
./scripts/audit-maintained-repositories.sh
```

脚本逐仓输出 `PASS` 或带稳定错误码的 `FAIL`，任一仓库漂移时整体退出码为 `1`。参数或本地依赖错误退出码为 `2`。

发布安全相关错误码包括 `[RELEASE_MANIFEST]`、`[RELEASE_WORKFLOW]`、`[RELEASE_CONCURRENCY]`、`[ROLLBACK_TARGET]`、`[ROLLBACK_GUARD]`、`[ROLLBACK_CAPTURE]` 和 `[RELEASE_FAILURE_STATE]`；它们分别定位项目适配、发布入口、串行边界、不可变目标、路径 guard、步骤顺序和失败状态保持。`[CODE_REVIEW_RULES]` 表示根 `AGENTS.md` 缺失、不是普通文件，或 CommonMark 解析后不存在源码行精确等于 `## Code Review Rules` 的真实 h2；fenced code、HTML block、autolink 与 inline code 等边界由固定 markdown-it-py parser 判定。

审计覆盖：

- active PR/master workflows 的事件和权限边界；
- 根 `AGENTS.md` 的普通文件属性与精确 `## Code Review Rules` 标题；
- 所有 active workflow 的 self-hosted、`dev` Environment、secret、镜像拉取/编排和手动部署能力；受控 release 之外发现任一发布入口即 fail-closed；
- GitHub 平台内建的 `dynamic/dependabot/update-graph` 会被明确跳过；其他 active workflow 若无法从 `master` 读取则 fail-closed；
- 固定 PR 检查名与 runner 边界；
- 外部 Action 的 40 位 SHA 和版本注释；
- `dev` Environment、active workflow 所引用的 secret 名称边界；
- `.github/release-safety.yml` 的 schema、语义 job/step 引用、依赖、condition 映射和步骤全序；
- `rollback_sha`/原因输入、发布与回滚串行锁、Environment、失败状态及成功后清理等可由结构化 YAML 可靠判断的高层约束；
- 项目发布安全契约 wrapper 是 Git tree 中 mode `100755` 的普通文件；`PR container validation` job 名称在所有 active workflow 中唯一，job 无 `if`、无 `needs`、无有效 `continue-on-error`，workflow/job 不得覆盖默认 `shell` 或 `working-directory`；稳定步骤必须以单行 `run` 精确执行该路径，不带参数、前后命令、管道或兜底逻辑，也不得声明 `if`、`continue-on-error`、`shell` 或 `working-directory`；
- prepare 存在时，publish、migration 与 deploy 只能共享 manifest 映射 prepare job 的同一个合法 output signal，deploy 还必须让正常与回滚路径共同受 `needs.<prepare>.result == 'success'` 约束；prepare 不存在时只能共享 `github.event.inputs.rollback_sha`，手动回滚分支还必须显式限定 `workflow_dispatch`；
- release workflow 的所有 job 都不得启用 `continue-on-error`；发布与回滚 concurrency 只能使用常量、允许的 `github.repository/workflow/ref/ref_name`，或仅由这些 context 构成的 `format(...)`；
- publish/deploy/finalize 的 master 边界、normal/rollback 分支、migration 跳过回滚和 rollback 允许式不能只靠 manifest 自我声明，中央会独立验证公共语义；
- release 内未声明的特权 job、job 级写权限、动态分域 concurrency 和未锁定 digest 的 `docker://` Action；
- `master` branch protection 和 required check。
- 纳管产品仓库关闭 Auto-merge；分支自动删除按项目真实分支模型配置，不由公共审计强制。人工合并前的 Review/thread/风险分类仍由真实 PR 验收。

中央审计明确不解释任意 shell 的控制流，也不尝试从注释、`echo`、here-doc、字符串或脚本名证明 ref/内容 ID 比对、容器内 smoke、回滚命令及实际 `DEPLOY_TARGET_SHA`。它也不抓取官方页面或私有接口来判断 Automatic reviews 设置、模型审查质量、同一 HEAD 请求次数、在途 Review 或审查轮次预算；这些事实分别由项目可执行契约测试、真实发布验收和真实 PR 时间线负责。模板只是一种可复制 profile，`.github/release-safety.yml` 才是每个项目拓扑的声明式适配层。

本地 fixture 自测：

```bash
bash tests/test-audit.sh
```

## 自动漂移审计

自动审计只在基线仓库的 `.github/workflows/baseline-drift-audit.yml` 中运行。纳管项目不复制 workflow，也不保存审计凭据。中央任务通过 `actions/create-github-app-token` 创建短期 GitHub App installation token，并在 Action 输入中把 token 精确限制到 `repositories.txt` 对应的四个仓库。

GitHub App 名为 `Engineering Baseline Auditor`，只允许安装到 `@HyxiaoGe`。它不订阅 webhook 事件，不授予写权限，只配置以下 repository permissions：

- `Administration: read`：读取 `master` branch protection。
- `Actions: read`：列举 active workflows。
- `Contents: read`：读取默认分支 workflow 与本地 Action 内容。
- `Environments: read`：读取 Environment 和 Environment secret 名称元数据。
- `Metadata: read`：GitHub App installation token 强制携带的仓库元数据只读权限。
- `Secrets: read`：读取 repository secret 名称元数据。

基线仓库使用 repository variable `BASELINE_AUDIT_APP_CLIENT_ID` 保存 Client ID，并把私钥作为 `BASELINE_AUDIT_APP_PRIVATE_KEY` 存入 `audit` Environment；workflow 自身只声明 `contents: read`，创建短期令牌时再次显式要求上述五项 `read`。审计器只处理 secret 名称，GitHub API 和脚本都不会读取 secret 值。

接入新项目时必须在同一个基线 PR 中完成三处对齐：

1. 把 `owner/repo` 加入 `repositories.txt`。
2. 把仓库名加入中央 workflow 的 `repositories` 显式列表。
3. 把 GitHub App 安装范围扩展到该仓库。

合并后在基线仓库人工触发一次 `Engineering baseline drift audit`，确认全部仓库输出 `PASS owner/repo`。任何 API 无权读取、清单不一致或结构不完整都会 fail-closed，不能把跳过当成通过。计划任务按 Asia/Shanghai 周一 02:23 运行；GitHub 的 `schedule` 可能延迟，规则正确性以运行结论为准。

## 不由模板决定的内容

项目自行决定语言、包管理器、测试命令、job/step ID、是否需要 prepare/finalize、端口、容器名、镜像名、迁移步骤、服务数量、smoke URL/命令和通知实现。模板只是一种 profile，不是中央审计的事实源；项目必须按真实拓扑维护 `.github/release-safety.yml`，并结合真实行为完成验证。

数据库迁移必须采用 expand/contract，禁止自动执行 `alembic downgrade`；镜像恢复只恢复应用运行态，不宣称回滚数据库。捕获的旧 ref 必须是受管 `IMAGE_NAME:<40 位小写 SHA>`，内容 ID 必须是 `sha256:<64 位小写十六进制>`。首次部署没有可捕获的旧镜像时默认 fail-closed，若必须放行，应走独立的一次性审批与可审计例外，完成后立即恢复标准门禁。

手动回滚不使用第二份 workflow：在现有 release 的 `workflow_dispatch` 填写 40 位小写 `rollback_sha` 和非空原因。同一 deploy job 使用该值作为 `DEPLOY_TARGET_SHA`，跳过 publish 和迁移，完成身份与容器内 smoke；留空两个输入则仍补跑当前 `GITHUB_SHA`。
