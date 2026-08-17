# AGENTS.md — PROJECT_REPLACE

本文件用于声明项目内部实现、验证和交付方式。跨项目共同安全边界以 `HyxiaoGe/engineering-baseline` 的 `contracts/ci-cd-baseline.md` 为事实源。

## 语言与提交

- 所有回复、代码注释和 Git 提交信息使用中文。
- Git 提交标题使用 `<type>: <中文描述>`。
- 提交正文说明背景、改动和验证；AI 协作的提交追加 `Co-Authored-By:` trailer，署名与邮箱取实际使用的助手，不要混用不同厂商的名称与邮箱域。

## 规则优先级与覆盖边界

- 仓库根目录的本文件补充项目级规则，不复制或降低工程基线中的公共 MUST。
- 子目录 `AGENTS.md` 只在对应目录树内覆盖实现细节，例如测试命令、模块边界和验收路径。
- 子目录规则不得降低公共 MUST，包括 PR 权限隔离、受保护分支发布边界、Action SHA、Environment secret、凭据隔离、分支保护及部署身份/健康验收。
- 项目确需改变公共 MUST 时，先向 `engineering-baseline` 提交契约变更并通过全部纳管仓库审计；在此之前采用更严格的现有规则。

## 开发工作流

- 非平凡变更在独立 Git worktree 和独立分支中完成，禁止污染长期开发目录。
- 调查任务默认只读；获得“开始、继续、修下、按你说的来”等实现授权后，推进到当前授权允许的最远交付边界。
- 行为修复和新能力优先先补失败测试，再实现最小完整改动。
- 保留用户已有改动，只暂存当前任务文件；禁止用 destructive Git 命令清理工作区。
- 提交前核对分支、状态、暂存差异、敏感信息和与任务匹配的测试/构建结果。

## Code Review Rules

### 阻塞边界

- 只提交 P0/P1 finding：问题必须由当前 PR 引入、存在当前可达的触发路径，并会造成明确的正确性、安全、权限、数据、兼容性或发布后果；评论必须说明触发条件、实际影响和最小安全路径，证据不足则不报告。
- P2/P3、纯防御性加固、需要未来维护者同时修改规则与测试才成立的假设、测试还可增加更多 fixture、lint/格式/措辞/命名或无当前影响的重构默认不报告，也不得仅因建议有价值就阻塞合并。

### 项目重点

- 检查数据/API 与跨仓协议兼容、CI/CD 权限边界、失败/回滚路径及测试能否证明这些高风险行为；机械一致性继续交给确定性 CI；项目重点：PROJECT_REPLACE_REVIEW_RULES

### Few-shot

正例：新增接口绕过现有授权校验，使普通用户能够读取他人数据；这是当前可达的安全后果，应提交 P1。

反例：还可以增加另一种输入形式的 fixture 或重命名 helper 以提升可维护性，但当前支持路径没有错误；这属于 P2/P3 加固，不提交 finding。

## CI/CD 公共门禁

- PR 只使用 GitHub 托管 runner，权限为 `contents: read`，不得读取发布 secret、绑定发布 Environment、推送镜像或部署。
- 受保护分支发布 job 和 secret 消费 job 绑定 `dev` Environment；真实部署 job 单独持有部署能力。
- 所有外部 Action 锁定完整 40 位 SHA并保留版本注释；checkout 设置 `persist-credentials: false`。
- Docker 凭据按 run、attempt 和 job 隔离并在 `always()` 中清理。
- 现有 release workflow 通过 `rollback_sha` 和非空原因处理手动回滚；普通发布和回滚共享 concurrency 与 deploy job，回滚模式跳过 publish 和迁移。
- 迁移与部署前捕获受管 `IMAGE_NAME:<40 位小写 SHA>` 和 `sha256:<64 位小写十六进制>` 内容 ID；候选及自动恢复后都核验这两个身份维度，并从运行容器内部执行项目健康或版本 smoke。
- 发布证据、metrics 和 finalize 使用实际 `DEPLOY_TARGET_SHA`；恢复成功不覆盖原发布失败，旧镜像只在验收成功后清理。
- 数据库迁移采用 expand/contract，禁止自动执行 `alembic downgrade`；首次部署无旧镜像时默认 fail-closed，例外必须一次性审批并留证。
- 发布、手动部署、self-hosted、`dev` Environment 和发布 secret 能力只存在于唯一受控 release workflow；按真实拓扑维护 `.github/release-safety.yml`，不要把模板 job/step ID 当成公共事实。
- 项目可执行契约测试负责证明 ref/内容 ID、容器内 smoke、回滚命令和实际目标 SHA；固定 `100755` wrapper 内部调用项目测试，`PR container validation` job 名称必须唯一、无依赖且无条件执行，workflow/job/targeted step 不得自定义 shell 或工作目录，targeted step 只以精确单行 `run` 执行 manifest 声明路径。中央审计只验证 manifest 与结构化 YAML 高层约束，不解释任意 shell 控制流。
- 受保护分支要求 GitHub Actions 产生的 `PR container validation`，启用 strict、管理员保护和对话解决，禁止 force push 与删除。
- 官方 Review 不是 required check 时，仓库保持 `allow_auto_merge=false`；只在 required checks 成功、阻塞 finding 已解决或有明确风险处置且 review thread 已完成处置后人工合并。只有仓库仅使用临时 PR head 分支，或所有长期 head 分支受保护时，才设置 `delete_branch_on_merge=true`。

## 项目命令

复制模板时必须替换以下占位符，不得将占位符提交到项目仓库：

```bash
PROJECT_REPLACE_TEST_COMMAND
PROJECT_REPLACE_LINT_COMMAND
PROJECT_REPLACE_BUILD_COMMAND
```

## 项目扩展说明

- 架构边界：PROJECT_REPLACE_ARCHITECTURE_RULES
- 本地运行授权：PROJECT_REPLACE_LOCAL_RUNTIME_POLICY
- dev 验收路径：PROJECT_REPLACE_DEV_ACCEPTANCE
- 关联仓库或协议消费者：PROJECT_REPLACE_RELATED_REPOSITORIES
