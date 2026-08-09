# 工程基线维护手册

本目录是 Fusion、Audio 与后续新项目共同使用的工程治理入口。公共契约只描述跨项目安全与交付边界；语言、构建命令、容器拓扑和业务验收继续由各项目负责。

## 日常审计

对当前维护清单执行一次只读 live 审计：

```bash
./scripts/audit-maintained-repositories.sh
```

审计器只读取 GitHub 配置、工作流内容和 secret 名称，不读取 secret 值。任何仓库失败时整体退出码为 `1`；本地依赖或清单错误退出码为 `2`。

以下情况必须执行审计并保存结果：

- 公共契约、模板或审计器发生变化；
- 根 `AGENTS.md` 或 `## Code Review Rules` 发生变化；
- 任一项目新增或修改 PR、发布、部署 workflow；
- required check、branch protection、Environment 或 secret scope 发生变化；
- 新项目首次接入，以及接入后的首个 master 发布完成后。

## 新项目接入

1. 在独立 worktree 中复制 `templates/AGENTS.md`，替换占位符并补齐项目内部规则；项目规则不得降低公共 MUST，根文件必须保留精确 `## Code Review Rules` 标题。
2. 在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`，并用真实 PR 验证自动审查；未触发或需要重审时使用 `@codex review`。
3. 保持 Auto-merge 关闭；官方 Review 尚非 required check 时不得为单个 PR 开启 Auto-merge。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才启用合并后自动删除远端分支。
4. 复制并按项目实际情况改造 `templates/` 下的 PR、release workflow、`release-safety.yml` 与 `release-safety-contract.sh`；把后两者分别安装为 `.github/release-safety.yml` 与 `.github/scripts/release-safety-contract.sh`，保持 wrapper 的 Git mode 为 `100755`，并映射项目真实 job/step 拓扑。
5. 通过真实 PR 证明 `PR container validation` 成功，随后原子迁移 master required check。
6. 通过一次 master 发布证明 Environment-only secret、旧运行态捕获、候选镜像身份、容器内 smoke、成功后清理和 `DEPLOY_TARGET_SHA` 发布证据。
7. 将 `owner/repo` 追加到 `repositories.txt`。
8. 将仓库名追加到中央 `.github/workflows/baseline-drift-audit.yml` 的 `repositories` 显式列表；测试会要求该列表与清单顺序一致。
9. 把只读 GitHub App `Engineering Baseline Auditor` 的安装范围扩展到新仓库；纳管项目不得保存 App 私钥或个人访问令牌。
10. 运行 fixture 测试，并在基线仓库人工触发中央 live 审计；两者都成功后才算纳入基线。

固定 wrapper 内部可以复用既有语言或容器测试；`PR container validation` job 名称必须全局唯一、无 `if`、无 `needs`、无有效 `continue-on-error`，workflow/job 不得覆盖默认 `shell` 或 `working-directory`。manifest 映射的主 PR targeted step 必须以单行 `run` 精确等于 wrapper 路径，不能附加参数、前后命令、`;`、管道或 `||`，也不能声明 `if`、`continue-on-error`、`shell`、`working-directory`，或把 ID 挂到 checkout、`echo`、`test -f` 与不相关的完整构建步骤。

prepare 存在时，publish、migration 与 deploy 必须使用 `needs.<prepare>.outputs.<合法ID>` 指向同一个真实 output signal，deploy 的两条路径还必须共同要求 prepare 成功；prepare 不存在时只能使用 `github.event.inputs.rollback_sha`，且 deploy 的手动回滚分支必须同时要求 `github.event_name == 'workflow_dispatch'`。rollback step condition 只能由 `failure()`、mapped capture 成功和 mapped candidate 已进入三类原子各一次组成。release workflow 的所有 job 都必须保持失败可见，concurrency 不得按 inputs、matrix、job 或运行编号分域。

## 修改公共规则

1. 先在 `contracts/ci-cd-baseline.md` 或 `contracts/codex-code-review.md` 明确公共 MUST 与项目扩展点，避免把单个项目细节升格为通用规则。
2. 为审计器补充能够复现旧实现缺口的失败 fixture，取得 RED 后再修改实现。
3. 同步模板 profile、manifest schema、已知 Action SHA/版本映射和 README。
4. 执行：

   ```bash
   bash tests/test-audit.sh
   ./scripts/audit-maintained-repositories.sh
   ```

5. 检查四仓真实 PR、master 发布和运行环境证据；只读审计不能替代这些门禁。

## 官方 Codex Code Review 维护

- 只采用官方 Codex Code Review，不自建 Reviewer、GitHub Action、Bot、Webhook 服务、模型调用或平行评论协议。
- 自动触发依赖官方 `Automatic reviews`；`AGENTS.md` 只定义审查规则，不能代替设置。自动审查未出现或需要重审时使用 `@codex review`。
- v1 保持观察模式，不把官方 Review 增加为 required check，不修改现有 branch protection，也不要求官方输出自定义批准口令或严重级别。
- 官方设置和审查行为通过真实 PR 验收；中央审计只检查根 `AGENTS.md` 是普通文件，且固定 `markdown-it-py==3.0.0` CommonMark parser 产生源码行精确等于 `## Code Review Rules` 的真实 h2。不得恢复手写 Markdown 状态机，也不抓取页面或调用私有接口。
- 官方功能演进时先更新接入说明和精简规则；若官方补齐缺口，优先删除临时流程，不维护平行实现。

## Auto-merge 维护

- GitHub 只保证无写权限者推送新提交时关闭 Auto-merge；有写权限者推送后不保证自动关闭。官方 Review 当前不是 required check，因此 v1 暂不允许仓库或单个 PR 开启 Auto-merge。
- 不建立 HEAD 监听器、自动合并 Bot、Action 或定时任务来补这个能力缺口；未来等官方 Review 可成为当前 HEAD required gate，或 GitHub 保证任意新提交都会撤销 Auto-merge 后再评估。
- 人工合并前确认官方 Review 当前 HEAD、全部 review thread 已解决、required checks 成功且风险已分类；新提交必须重新 Review。
- Dependabot PR 不能只凭 CI 绿灯自动合并；运行时依赖、跨大版本和会触发生产发布的仓库必须另做兼容性与发布授权判断。
- 分支自动删除不是公共强制项。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才启用 GitHub 的合并后自动删除；存在未保护且需要复用的长期 head 分支时必须关闭。
- 本地 worktree/分支只在已合并、干净、没有独有提交且相关发布验收完成后删除。

## Action 升级

- 只接受上游官方 release 对应的完整 40 位 commit SHA。
- 同时更新模板、审计器 `KNOWN_ACTIONS`、契约中的版本表和相关 fixture。
- 通过真实 PR 验证后再合并；不得先改 required check 或回退为浮动 tag。

## 发布基线版本

1. 先让基线仓库的 `Baseline contract validation` 在真实 PR 通过。
2. 合并后人工触发 `Engineering baseline drift audit`，保存四仓 live 结果。
3. 只有四仓都输出 `PASS`，才更新版本说明并把该版本作为后续新项目入口。
4. 中央审计的 GitHub App `Engineering Baseline Auditor` 只允许 `Administration: read`、`Actions: read`、`Contents: read`、`Environments: read`、`Metadata: read`、`Secrets: read`，不订阅 webhook 事件且不授予写权限；其中 Metadata 是 GitHub 强制只读权限。
5. App Client ID 使用 repository variable；私钥只存放在基线仓库的 `audit` Environment。禁止把 App 私钥下发到项目，也禁止保存个人访问令牌。

## 发布安全演练

1. 正常 master 发布使用 merge SHA 作为 `DEPLOY_TARGET_SHA`，保存候选 ref、内容 ID、容器内 smoke 和 finalize 证据。
2. 人工触发现有 release workflow，填写已存在镜像的 40 位小写 `rollback_sha` 与非空原因；确认 publish 登录/构建/push 和迁移全部跳过。
3. 演练候选部署或验收失败，确认 capture 只接受受管 `IMAGE_NAME:<40 位小写 SHA>` 和 `sha256:<64 位小写十六进制>` 内容 ID，且只在 capture 成功、候选部署已进入后自动恢复；恢复后同时核对旧 image ref、内容 ID 并执行容器内 smoke。
4. 确认原发布仍为失败；恢复失败也不得被隐藏，旧镜像清理不得以 `always()` 运行。发布证据、metrics 和 finalize 必须记录实际 `DEPLOY_TARGET_SHA`。
5. 迁移只采用 expand/contract，禁止自动执行 `alembic downgrade`；应用镜像恢复不执行数据库降级。
6. 首次部署无旧镜像时默认 fail-closed。确需首次部署时，单独审批一次性例外并保存证据，不得长期弱化 capture 门禁。
7. 检查所有 active workflow；self-hosted、`dev` Environment、secret、镜像拉取/编排或手动部署能力不得散落在受控 release 之外，注释或 `echo` 文本不能作为运行时安全证据。
8. 中央审计只验证 manifest 与结构化 YAML 高层约束，不解释任意 shell 控制流；ref/内容 ID、容器内 smoke、回滚命令和实际目标 SHA 必须由项目可执行契约测试与真实演练证明。
9. 同步修改 workflow 与 manifest 不能覆盖公共语义：publish/deploy/finalize 必须 master guarded，publish/migration 必须跳过 rollback，deploy 必须显式区分 publish success 与 rollback+publish skipped，rollback 只能使用允许的 failure/capture/candidate 合取式。

## 漂移处理

- 先依据稳定错误码定位公共 MUST，例如 `[ACTION_PIN]`、`[REQUIRED_CHECK_APP]`、`[SECRET_ENV_BOUNDARY]`、`[CODE_REVIEW_RULES]`、`[RELEASE_MANIFEST]`、`[ROLLBACK_CAPTURE]` 或 `[RELEASE_FAILURE_STATE]`。
- 所有持久修复都从目标仓库的独立分支经 PR 进入 master，不直接修改 dev 服务器代码。
- 修复后重新执行目标仓库 PR、master 发布、部署身份/健康验收和全清单审计。
- 新的通用缺口必须沉淀为 fixture；只修项目而不增强审计器，会留下相同漂移再次发生的入口。
