# AGENTS.md — PROJECT_REPLACE

本文件用于声明项目内部实现、验证和交付方式。跨项目共同安全边界以 `HyxiaoGe/engineering-baseline` 的 `contracts/ci-cd-baseline.md` 为事实源。

## 语言与提交

- 所有回复、代码注释和 Git 提交信息使用中文。
- Git 提交标题使用 `<type>: <中文描述>`。
- 提交正文说明背景、改动和验证，并包含 `Co-Authored-By: Codex <noreply@anthropic.com>`。

## 规则优先级与覆盖边界

- 仓库根目录的本文件补充项目级规则，不复制或降低工程基线中的公共 MUST。
- 子目录 `AGENTS.md` 只在对应目录树内覆盖实现细节，例如测试命令、模块边界和验收路径。
- 子目录规则不得降低公共 MUST，包括 PR 权限隔离、master 发布边界、Action SHA、Environment secret、凭据隔离、分支保护及部署身份/健康验收。
- 项目确需改变公共 MUST 时，先向 `engineering-baseline` 提交契约变更并通过全部纳管仓库审计；在此之前采用更严格的现有规则。

## 开发工作流

- 非平凡变更在独立 Git worktree 和独立分支中完成，禁止污染长期开发目录。
- 调查任务默认只读；获得“开始、继续、修下、按你说的来”等实现授权后，推进到当前授权允许的最远交付边界。
- 行为修复和新能力优先先补失败测试，再实现最小完整改动。
- 保留用户已有改动，只暂存当前任务文件；禁止用 destructive Git 命令清理工作区。
- 提交前核对分支、状态、暂存差异、敏感信息和与任务匹配的测试/构建结果。

## CI/CD 公共门禁

- PR 只使用 GitHub 托管 runner，权限为 `contents: read`，不得读取发布 secret、绑定发布 Environment、推送镜像或部署。
- master 发布 job 和 secret 消费 job 绑定 `dev` Environment；真实部署 job 单独持有部署能力。
- 所有外部 Action 锁定完整 40 位 SHA并保留版本注释；checkout 设置 `persist-credentials: false`。
- Docker 凭据按 run、attempt 和 job 隔离并在 `always()` 中清理。
- 部署后精确比较运行镜像与本次 `GITHUB_SHA`，并从运行容器内部执行项目健康或版本 smoke。
- `master` 要求 GitHub Actions 产生的 `PR container validation`，启用 strict、管理员保护和对话解决，禁止 force push 与删除。

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
