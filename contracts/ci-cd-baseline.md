# CI/CD 公共契约

本文只定义跨项目共同 MUST。项目内部细节不得被误升格为公共规则。

## 1. 变更隔离

- MUST：非平凡工程改动在独立 Git worktree 和独立分支中完成。
- MUST：提交前核对 worktree、分支、暂存范围和未跟踪文件，保留用户已有改动。
- 项目扩展点：worktree 路径、分支名、提交拆分方式。

## 2. PR 事件与最小权限

- MUST：PR workflow 只由面向 `master` 的 `pull_request` 触发。
- MUST：PR job 只使用 GitHub 托管 `ubuntu-latest`，固定 job 显示名为 `PR container validation`。
- MUST：顶层权限为 `contents: read`，不得授予任何 write 权限。
- MUST：不得引用 secrets、绑定 Environment、使用 self-hosted runner、登录或推送镜像、执行部署。
- MUST：执行足以证明可合并性的完整测试和容器构建，但不发布构建产物。
- 项目扩展点：安装、lint、测试、构建命令和临时镜像名。

## 3. master 发布与手动回滚权限

- MUST：同一 release workflow 同时处理 `master` push、普通人工补跑和手动回滚；不得另建一份会重复编排的回滚 workflow。
- MUST：发布和回滚在同一 workflow 中共用非空 concurrency，且 `cancel-in-progress: false`，保证同一部署目标串行变更；不同项目可以使用不同 group 名。
- MUST：concurrency group 不得使用 `event_name`、事件输入、`inputs`、SHA、run ID/attempt 或 `head_ref` 等把普通发布与回滚分到不同锁域的动态量；允许常量或 repository/workflow/ref 维度。
- MUST：`workflow_dispatch` 只提供可选 `rollback_sha` 与 `rollback_reason`；输入只经固定 `env` 进入 shell，不得把事件输入直接插入命令。
- MUST：`rollback_sha` 非空时精确校验为 40 位小写 SHA，且 `rollback_reason` 非空；普通人工补跑仍选择当前 `GITHUB_SHA`。
- MUST：回滚模式整体跳过 publish job 中的 registry 登录、构建和 push，迁移步骤也必须明确跳过；候选镜像只能是 `IMAGE_NAME:DEPLOY_TARGET_SHA`，禁止 mutable tag 或派生 tag。
- MUST：可选 prepare job 只能是无 Environment、无 secret、无部署能力的 GitHub-hosted 纯校验；项目通过 manifest 声明实际 condition 与 needs，不要求统一 job ID 或输出名。
- MUST：publish 与 deploy condition 都由顶层合取的 master guard 支配；publish 顶层合取显式排除 rollback，deploy 使用 `always()` 并显式区分 publish success 的普通路径与 rollback 已确认且 publish skipped 的回滚路径。
- MUST：可选 finalize condition 由顶层合取的 `always()` 与 master guard 支配；release 内任何 job 级 `permissions` 不得超过 `contents: read`。
- MUST：发布镜像的 job 绑定 `dev` 且设置 `deployment: false`；实际部署 job 绑定 `dev`。
- MUST：引用发布 secret 的每个 job 都绑定 `dev`，active workflow 引用的自定义 secret 只存在于 Environment scope。
- MUST：Docker 客户端凭据使用包含 `GITHUB_RUN_ID` 与 `GITHUB_RUN_ATTEMPT` 的隔离目录，并在 `always()` 步骤清理。
- 项目扩展点：runner 标签、registry、凭据名称、构建和发布命令、prepare/finalize 是否存在、job/step ID、needs 与 target 输出表达式。

## 4. 供应链锁定

- MUST：所有 active workflows 以及 `.github/actions/**/action.yml` 中的外部 `uses:` 都锁定到 40 位 commit SHA。
- MUST：SHA 后保留可读版本注释，例如 `# v6`、`# v4.6.0`。
- MUST：每个 `actions/checkout` 步骤都在自身 `with` mapping 中显式设置 `persist-credentials: false`；顶层 `env` 或 `run` 字符串不能替代该设置。
- MUST：本地 Action 可以用相对路径，但其 manifest 中的外部 Action 同样受本规则约束。
- MUST：`docker://` Action 只接受 `@sha256:` 加 64 位小写十六进制内容摘要，mutable tag 或未锁定引用一律拒绝。
- 项目扩展点：选择哪些官方/第三方 Action；升级版本时同时更新 SHA、版本注释和契约测试。

## 5. 部署验收、自动恢复与迁移

- MUST：在迁移和候选运行态变更前，捕获当前容器 `.Config.Image` 的旧 image ref 与 `.Image` 的内容 ID；旧 ref 必须精确属于受管 `IMAGE_NAME` 且 tag 为 40 位小写 SHA，内容 ID 必须为 `sha256:` 加 64 位小写十六进制，任一不符都 fail-closed。
- MUST：候选部署步骤在调用项目编排前记录 `entered=true`；只有 capture 成功、候选部署实际进入且后续发生 `failure()` 时才自动恢复旧运行态。
- MUST：候选验收同时读取 `.Config.Image` 和 `.Image`，前者精确等于 `IMAGE_NAME:DEPLOY_TARGET_SHA`、后者非空，并从运行容器内部执行 readiness/version smoke。
- MUST：自动恢复脚本同时接收旧 image ref 与内容 ID；恢复后必须再次比对这两个值并执行容器内 smoke。
- MUST：自动恢复成功不能抹平原发布失败；自动恢复失败也不得通过 `continue-on-error` 隐藏。旧镜像清理只能以 `success()` 在候选验收成功后运行。
- MUST：发布证据、metrics、通知和 finalize 使用实际 `DEPLOY_TARGET_SHA`，手动回滚时不得错误记录触发 workflow 的 `github.sha`。
- MUST：数据库变更采用 expand/contract；禁止自动执行 `alembic downgrade`。镜像自动恢复不等同于数据库回滚。
- MUST：首次部署没有旧运行镜像时默认 fail-closed；项目确需首次部署，必须使用显式、一次性、可审计的例外流程，不能伪造旧镜像输出。
- MUST：项目提供 Git mode `100755` 的固定发布安全契约 wrapper，内部调用项目语言或容器测试并覆盖不可变目标、旧 ref/内容 ID、候选与恢复验收、容器内 smoke、失败状态和实际目标 SHA；`PR container validation` job 名称全局唯一、无 `if`、无 `needs`、无有效 `continue-on-error`，workflow/job 不得覆盖默认 `shell` 或 `working-directory`；manifest 映射的主 PR targeted step 以精确单行 `run` 执行 wrapper，不得声明 `if`、`continue-on-error`、`shell`、`working-directory`，也不得附加参数、前后命令、管道、`;` 或 `||`。
- 项目扩展点：容器名、编排脚本、端口、readiness URL、版本 endpoint、向前迁移实现、健康判定字段和多容器拓扑；中央审计只检查 workflow 结构，不静态理解任意项目脚本。

## 6. master 分支保护

- MUST：required status checks 启用 strict，并要求 GitHub Actions app 产生的 `PR container validation`。
- MUST：要求通过 Pull Request、对管理员执行保护、要求解决对话、禁止 force push、禁止删除 `master`。
- MUST：迁移检查名时先让新检查在真实 PR 成功，再原子替换旧 required check。
- MUST：官方 Review 尚不能作为当前 HEAD 的 required check 时，仓库关闭 Auto-merge。人工合并边界由官方 Review 治理契约决定，不能仅凭 CI 通过合并；分支自动删除按项目分支模型配置，不作为 CI/CD 公共门禁。
- 项目扩展点：额外 required checks，例如 CodeQL、语言专项检查或合规扫描。

## 7. Environment 与 secret 边界

- MUST：存在名为 `dev` 的 GitHub Environment。
- MUST：active workflows 使用的自定义发布 secrets 都存在于 `dev` Environment。
- MUST：secret context 必须能静态完整列举名称；禁止动态 `secrets[format(...)]` 与 `secrets: inherit`。
- MUST：完成 Environment-only 发布证明后，清理同名和遗留 repository secrets。
- MUST：审计和排障只处理 secret 名称，不读取、记录或回显 secret 值。
- 项目扩展点：secret 名称、Environment 审批规则、部署分支策略和生产环境层级。

## 8. 规则漂移

- MUST：定期或在基线变更后运行只读审计；任一公共 MUST 漂移都返回非零退出码。
- MUST：审计 active workflows、`.github/actions`、live `master` protection、`dev` Environment 以及 repo/env secret 名称边界。
- MUST：逐一分类所有 active workflow；任何包含 self-hosted runner、`dev` Environment、secret、镜像拉取/编排/部署命令或人工部署入口的发布能力，只能存在于唯一受控 release workflow。
- MUST：每个项目维护 `.github/release-safety.yml`，声明受控 workflow、可选 prepare/finalize、publish/deploy、target/capture/migration/candidate/verify/rollback/cleanup/failure 语义角色、needs/condition 映射、项目契约测试文件和主 PR 稳定 step ID。模板只是一种 profile，不是事实源。
- MUST：prepare 存在时，回滚 signal 只能是 `needs.<映射 prepare>.outputs.<合法ID>`，且必须被 publish negative、migration negative 与 deploy positive 全链一致引用；deploy 的正常与回滚路径必须共同要求 mapped prepare result 成功。prepare 不存在时 signal 精确为 `github.event.inputs.rollback_sha`，deploy 回滚分支还必须显式限定 `workflow_dispatch`。
- MUST：deploy 的 normal/rollback 两分支只允许声明的 publish result、同一 rollback signal 和必要的 dispatch guard；不得加入字符串常量 decoy、恒假原子或未知条件。release workflow 所有 job 的 `continue-on-error` 只能缺失或显式 false。
- MUST：rollback step condition 只允许 `failure()`、mapped capture outcome success、mapped candidate outcome non-skipped 或 entered true 三类原子各恰好一次，不得添加 `false`、`success()`、矛盾条件或其他未知原子。
- MUST：finalize job 存在时，其 condition 只允许 `always()` 与 master ref 两类原子各恰好一次，不得添加恒假、矛盾或其他未知原子。
- MUST：发布/回滚共享的 concurrency group 只能由常量、`github.repository`、`github.workflow`、`github.ref`、`github.ref_name` 或仅使用这些 context 的 `format(...)` 构成。
- MUST：中央审计验证 manifest schema、引用唯一存在、事件/权限/Environment、非空串行 concurrency、结构化 needs/condition 映射、步骤全序、rollback 的 `failure()` 与 capture/candidate 引用、成功后 cleanup 和失败保持；不要求统一 env、output、job ID 或 concurrency group 名。
- MUST：manifest condition 只是项目表达式映射，不能自我证明安全；中央另行验证 master 支配、publish/migration 排除 rollback、deploy normal/rollback 分支、rollback 允许式及 finalize always+master。同步改坏 workflow 与 manifest 必须失败。
- MUST：release workflow 内未声明 job 一旦含 self-hosted、Environment、secret、本地 Action 或部署能力就 fail-closed；`continue-on-error` 只有缺失、`false` 或 `${{ false }}` 视为关闭。
- MUST：中央审计不声称从原始 shell 文本证明控制流可达性；注释、`echo`/`printf`、here-doc、字符串常量和多行 `if false` 的真假由项目可执行契约测试负责，运行时结果再由真实发布验收负责。
- MUST：中央自动审计使用短期 GitHub App installation token，并把 token 显式限制到 `repositories.txt` 中的仓库；不得保存个人令牌，也不得把审计凭据下发到纳管项目。
- MUST：审计 App 只授予读取 Administration、Actions、Contents、Environments 和 Secrets 元数据所需的仓库权限，短期令牌创建步骤再次显式要求这五项 `read`；不订阅 webhook 事件，不授予写权限。
- MUST：审计不能替代真实 PR、master 发布和运行环境验收；三者证据需要同时成立。
- 项目扩展点：审计调度频率、通知渠道、额外仓库规则。

## 9. AGENTS.md 覆盖边界

- MUST：新项目从 `templates/AGENTS.md` 建立仓库根级协作规则，并替换全部 `PROJECT_REPLACE` 占位符。
- MUST：项目级和子目录 `AGENTS.md` 可以定义内部架构、命令、运行环境和验收细节，但不得降低本契约中的公共 MUST。
- MUST：需要改变公共 MUST 时，先修改本契约、模板和审计 fixture，并证明全部纳管仓库继续通过；不能只在单个项目里静默例外。
- MUST：规则发生冲突且尚未完成公共契约迁移时，采用更严格的现有规则。
- 项目扩展点：语言、目录边界、测试命令、本地服务策略、真实用户路径和跨仓协议。

## 基线与模板当前固定的外部 Action

| Action | 完整 SHA | 版本注释 |
|---|---|---|
| `actions/checkout` | `d23441a48e516b6c34aea4fa41551a30e30af803` | `v6` |
| `actions/create-github-app-token` | `bcd2ba49218906704ab6c1aa796996da409d3eb1` | `v3` |
| `actions/setup-node` | `249970729cb0ef3589644e2896645e5dc5ba9c38` | `v6` |
| `docker/login-action` | `dbcb813823bdd20940b903addbd779551569679f` | `v4.6.0` |

这些 SHA 来自已经验证过的 Fusion/Audio 基线版本。升级必须通过 PR 和契约测试，不允许改回浮动 tag。
