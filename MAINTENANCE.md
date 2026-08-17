# 工程基线维护手册

本文是操作手册。公共 MUST 只在契约中定义，这里不复述规则，只描述"什么时候做什么"。

- [contracts/ci-cd-baseline.md](contracts/ci-cd-baseline.md)：CI/CD 公共契约
- [contracts/codex-code-review.md](contracts/codex-code-review.md)：官方 Codex Code Review 治理契约
- [contracts/error-codes.md](contracts/error-codes.md)：结论行、退出码与错误码参考
- [CHANGELOG.md](CHANGELOG.md)：基线版本变更记录

## 日常审计

对当前维护清单执行一次只读 live 审计：

```bash
./scripts/audit-maintained-repositories.sh
```

审计器只读取 GitHub 配置、工作流内容和 secret 名称，不读取 secret 值。

结论分三类，不能混为一谈：

- `FAIL` + 退出码 `1`：**基线漂移**，按错误码定位公共 MUST 并修复。
- `ERROR` + 退出码 `3`：**审计没跑完**（GitHub 5xx/429/网络失败），结论不可信。先确认 GitHub 状态并重跑，不要当成漂移去改项目，也不能当成通过。
- 退出码 `2`：参数、仓库清单或本地依赖错误。

以下情况必须执行审计并保存结果：

- 公共契约、模板或审计器发生变化；
- 根 `AGENTS.md` 或 `## Code Review Rules` 发生变化；
- 任一项目新增或修改 PR、发布、部署 workflow；
- required check、branch protection、Environment 或 secret scope 发生变化；
- 新项目首次接入，以及接入后的首个受保护分支发布完成后。

## 新项目接入

1. 在独立 worktree 中复制 `templates/AGENTS.md`，替换占位符并补齐项目内部规则；项目规则不得降低公共 MUST，根文件必须保留精确 `## Code Review Rules` 标题。
2. 在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`，并用真实 PR 验证自动审查。
3. 保持 Auto-merge 关闭；分支自动删除按项目真实分支模型配置。
4. 复制并按项目实际情况改造 `templates/` 下的 PR、release workflow、`release-safety.yml` 与 `release-safety-contract.sh`；把后两者分别安装为 `.github/release-safety.yml` 与 `.github/scripts/release-safety-contract.sh`，保持 wrapper 的 Git mode 为 `100755`，并映射项目真实 job/step 拓扑。
5. 通过真实 PR 证明 `PR container validation` 成功，随后原子迁移受保护分支的 required check。
6. 通过一次受保护分支发布证明 Environment-only secret、旧运行态捕获、候选镜像身份、容器内 smoke、成功后清理和 `DEPLOY_TARGET_SHA` 发布证据。
7. 将 `owner/repo` 追加到 `repositories.txt`。
8. 将仓库名追加到中央 `.github/workflows/baseline-drift-audit.yml` 的 `repositories` 显式列表；测试会要求该列表与清单顺序一致。
9. 把只读 GitHub App `Engineering Baseline Auditor` 的安装范围扩展到新仓库；纳管项目不得保存 App 私钥或个人访问令牌。
10. 运行 fixture 测试，并在基线仓库人工触发中央 live 审计；两者都成功后才算纳入基线。

默认分支不是 `master` 的项目，通过 `BASELINE_DEFAULT_BRANCH` 指定；该变量同时决定审计读取的 ref、`github.ref` guard 原子与 PR `branches` 判定。同一次审计的所有仓库共用一个值。

manifest 与 workflow 的具体映射约束见[公共契约](contracts/ci-cd-baseline.md) §5 与 §8。

## 修改公共规则

1. 先在 `contracts/ci-cd-baseline.md` 或 `contracts/codex-code-review.md` 明确公共 MUST 与项目扩展点，避免把单个项目细节升格为通用规则。
2. 为审计器补充能够复现旧实现缺口的失败 fixture，取得 RED 后再修改实现。
3. 同步模板 profile、manifest schema、已知 Action SHA/版本映射。
4. 新增或删除错误码时同步 `contracts/error-codes.md`；测试会双向校验实现与文档完全一致。
5. 执行：

   ```bash
   bash tests/test-audit.sh
   ./scripts/audit-maintained-repositories.sh
   ```

6. 检查各仓真实 PR、发布和运行环境证据；只读审计不能替代这些门禁。
7. 在 `CHANGELOG.md` 记录本次变更，并按语义化版本更新 `BASELINE_VERSION`。

### 审计器改动的额外要求

- 表达式解析、重试与分支解析这类纯函数改动，必须在 `tests/unit/` 补直接单元测试；只靠 fixture 间接覆盖不够。
- 新增"只在被引用时才解析"的输入源时，确认它在 `audit_repository` 的检查顺序中确实被覆盖——本地 Action 曾因此产生过审计盲区，见 `CHANGELOG.md` v1.1.0。

## 官方 Codex Code Review 维护

规则本身见[治理契约](contracts/codex-code-review.md)。日常只需要注意：

- 只采用官方 Codex Code Review，不自建 Reviewer、Bot、Webhook 服务或平行评论协议。
- 自动触发依赖官方 `Automatic reviews`；`AGENTS.md` 只定义审查规则，不能代替设置。自动审查未出现时先按官方说明排查，确认没有结果或在途信号后才使用 `@codex review`。
- `## Code Review Rules` 保持两到三条简洁、项目特有的高后果规则，并提供正反 few-shot；机械一致性、lint 和格式交给确定性 CI。
- 官方设置和审查行为通过真实 PR 验收；中央审计只检查根 `AGENTS.md` 是普通文件且含精确 h2 标题，不得恢复手写 Markdown 状态机。
- 官方功能演进时先更新接入说明和精简规则；若官方补齐缺口，优先删除临时流程。

## Auto-merge 维护

边界与理由见[治理契约](contracts/codex-code-review.md) §5。日常只需要注意：

- v1 暂不允许仓库或单个 PR 开启 Auto-merge；不建立监听器、Bot 或定时任务来补这个能力缺口。
- 人工合并前确认 required checks 成功、阻塞 finding 已修复或有明确风险接受、全部 review thread 已完成处置且依赖与发布风险已分类。
- Dependabot PR 不能只凭 CI 绿灯合并。
- 本地 worktree/分支只在已合并、干净、没有独有提交且相关发布验收完成后删除。

## Action 升级

- 只接受上游官方 release 对应的完整 40 位 commit SHA。
- 同时更新模板、审计器 `KNOWN_ACTIONS`、契约中的版本表和相关 fixture。
- 通过真实 PR 验证后再合并；不得先改 required check 或回退为浮动 tag。

## 发布基线版本

1. 先让基线仓库的 `Baseline contract validation` 在真实 PR 通过。
2. 合并后人工触发 `Engineering baseline drift audit`，保存各仓 live 结果。
3. 只有全部仓库输出 `PASS`，才更新 `CHANGELOG.md` 与 `BASELINE_VERSION`，打 `v<major>.<minor>.<patch>` tag，并把该版本作为后续新项目入口。
4. 中央审计的 GitHub App `Engineering Baseline Auditor` 只允许安装到 `@HyxiaoGe`，不订阅 webhook 事件且不授予写权限，只配置以下 repository permissions：

   - `Administration: read`：读取受保护分支的 branch protection。
   - `Actions: read`：列举 active workflows。
   - `Contents: read`：读取默认分支 workflow 与本地 Action 内容。
   - `Environments: read`：读取 Environment 和 Environment secret 名称元数据。
   - `Metadata: read`：GitHub App installation token 强制携带的仓库元数据只读权限。
   - `Secrets: read`：读取 repository secret 名称元数据。

5. App Client ID 使用 repository variable `BASELINE_AUDIT_APP_CLIENT_ID`；私钥只作为 `BASELINE_AUDIT_APP_PRIVATE_KEY` 存放在基线仓库的 `audit` Environment。禁止把 App 私钥下发到项目，也禁止保存个人访问令牌。
6. 计划任务失败时由独立 `notify` job 开或更新 issue。该 job 只使用基线仓库自身的 `GITHUB_TOKEN`，与只读审计 App 完全隔离；issue 正文只放运行链接，不回显可能包含 secret 名称的审计输出。

## 发布安全演练

1. 正常发布使用 merge SHA 作为 `DEPLOY_TARGET_SHA`，保存候选 ref、内容 ID、容器内 smoke 和 finalize 证据。
2. 人工触发现有 release workflow，填写已存在镜像的 40 位小写 `rollback_sha` 与非空原因；确认 publish 登录/构建/push 和迁移全部跳过。
3. 演练候选部署或验收失败，确认 capture 只接受受管 `IMAGE_NAME:<40 位小写 SHA>` 和 `sha256:<64 位小写十六进制>` 内容 ID，且只在 capture 成功、候选部署已进入后自动恢复；恢复后同时核对旧 image ref、内容 ID 并执行容器内 smoke。
4. 确认原发布仍为失败；恢复失败也不得被隐藏，旧镜像清理不得以 `always()` 运行。
5. 迁移只采用 expand/contract，禁止自动执行 `alembic downgrade`；应用镜像恢复不执行数据库降级。
6. 首次部署无旧镜像时默认 fail-closed。确需首次部署时，单独审批一次性例外并保存证据。
7. 检查所有 active workflow；发布能力不得散落在受控 release 之外，注释或 `echo` 文本不能作为运行时安全证据。
8. 中央审计只验证 manifest 与结构化 YAML 高层约束，不解释任意 shell 控制流；ref/内容 ID、容器内 smoke、回滚命令和实际目标 SHA 必须由项目可执行契约测试与真实演练证明。

## 漂移处理

- 先按 [contracts/error-codes.md](contracts/error-codes.md) 定位错误码对应的公共 MUST。
- 确认结论行是 `FAIL` 而不是 `ERROR`：后者是审计没跑完，应该先修基础设施再重跑。
- 所有持久修复都从目标仓库的独立分支经 PR 进入受保护分支，不直接修改 dev 服务器代码。
- 修复后重新执行目标仓库 PR、发布、部署身份/健康验收和全清单审计。
- 新的通用缺口必须沉淀为 fixture；只修项目而不增强审计器，会留下相同漂移再次发生的入口。
