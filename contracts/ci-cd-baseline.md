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

## 3. master 发布权限

- MUST：发布 workflow 只由 `master` push 触发；允许人工补跑时，`workflow_dispatch` 也只能发布 `master`。
- MUST：手动发布中的真实 publish/deploy job 必须自身使用精确的 `github.ref == 'refs/heads/master'` guard，或在没有自定义 `if` 时通过完整 `needs` 链继承已 guard 的前置 job；宽松布尔表达式不能作为 guard。
- MUST：发布镜像的 job 绑定 `dev` 且设置 `deployment: false`；实际部署 job 绑定 `dev`。
- MUST：引用发布 secret 的每个 job 都绑定 `dev`，active workflow 引用的自定义 secret 只存在于 Environment scope。
- MUST：Docker 客户端凭据使用包含 `GITHUB_RUN_ID` 与 `GITHUB_RUN_ATTEMPT` 的隔离目录，并在 `always()` 步骤清理。
- 项目扩展点：runner 标签、registry、凭据名称、构建和发布命令。

## 4. 供应链锁定

- MUST：所有 active workflows 以及 `.github/actions/**/action.yml` 中的外部 `uses:` 都锁定到 40 位 commit SHA。
- MUST：SHA 后保留可读版本注释，例如 `# v6`、`# v4.6.0`。
- MUST：每个 `actions/checkout` 步骤都在自身 `with` mapping 中显式设置 `persist-credentials: false`；顶层 `env` 或 `run` 字符串不能替代该设置。
- MUST：本地 Action 可以用相对路径，但其 manifest 中的外部 Action 同样受本规则约束。
- 项目扩展点：选择哪些官方/第三方 Action；升级版本时同时更新 SHA、版本注释和契约测试。

## 5. 部署验收与镜像身份

- MUST：部署后读取运行容器的 `.Config.Image`，精确等于本次预期镜像名加 `GITHUB_SHA`。
- MUST：smoke 从运行容器内部执行，验证服务真实监听地址及关键依赖，而非依赖可能已取消的宿主机端口。
- MUST：smoke 的版本或镜像身份最终关联到本次 `GITHUB_SHA`。
- 项目扩展点：容器名、端口、readiness URL、版本 endpoint、迁移顺序、健康判定字段和多容器拓扑。

## 6. master 分支保护

- MUST：required status checks 启用 strict，并要求 GitHub Actions app 产生的 `PR container validation`。
- MUST：要求通过 Pull Request、对管理员执行保护、要求解决对话、禁止 force push、禁止删除 `master`。
- MUST：迁移检查名时先让新检查在真实 PR 成功，再原子替换旧 required check。
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
- MUST：审计不能替代真实 PR、master 发布和运行环境验收；三者证据需要同时成立。
- 项目扩展点：审计调度频率、通知渠道、额外仓库规则。

## 模板当前固定的外部 Action

| Action | 完整 SHA | 版本注释 |
|---|---|---|
| `actions/checkout` | `d23441a48e516b6c34aea4fa41551a30e30af803` | `v6` |
| `actions/setup-node` | `249970729cb0ef3589644e2896645e5dc5ba9c38` | `v6` |
| `docker/login-action` | `dbcb813823bdd20940b903addbd779551569679f` | `v4.6.0` |

这些 SHA 来自已经验证过的 Fusion/Audio 基线版本。升级必须通过 PR 和契约测试，不允许改回浮动 tag。
