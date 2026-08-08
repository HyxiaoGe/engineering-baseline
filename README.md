# GitHub 工程基线

这是一套本地、可复用的 GitHub Actions 与仓库治理基线。它统一跨项目的安全边界和验收证据，不统一项目内部的构建方式。

当前目录不会自动创建 GitHub 仓库，也不会推送或修改任何项目。`scripts/audit-github-baseline.sh` 只通过 GitHub GET API 读取公开配置、工作流内容以及 secret **名称**，不会读取或输出 secret 值。

当前纳管仓库记录在 `repositories.txt`。公共规则的变更、Action 升级、新项目接入和漂移处理统一从 [MAINTENANCE.md](MAINTENANCE.md) 进入。

## 接入顺序

1. 从独立 Git worktree 创建变更分支，避免污染长期开发目录。
2. 复制 `templates/pr-ci.yml` 和 `templates/release.yml`，替换所有 `PROJECT_REPLACE` 项。
3. 在仓库内实现项目自己的 PR 验证、镜像发布、部署、容器内 smoke 和发布收尾脚本。
4. 创建 `dev` Environment，把发布所需 secret 移入该 Environment；确认发布成功后清理 repository-scope secrets。
5. 为 `master` 启用保护规则，要求 GitHub Actions 产生的 `PR container validation`，并保持 strict。
6. 在真实 PR 上先让新检查通过，再原子替换旧 required check；不要先删除旧门禁。
7. 合并后核对运行容器的实际镜像 tag 与 merge SHA，并执行容器内部 smoke。
8. 使用只读审计检查规则漂移。

完整 MUST 和项目扩展点见 [contracts/ci-cd-baseline.md](contracts/ci-cd-baseline.md)。

## 只读审计

前置条件：已安装并登录 `gh`，安装 `Python 3` 与 `PyYAML>=6`，当前身份对目标仓库至少具有读取 Actions、Environment、branch protection 和 secret 名称元数据的权限。

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

审计覆盖：

- active PR/master workflows 的事件和权限边界；
- GitHub 平台内建的 `dynamic/dependabot/update-graph` 会被明确跳过；其他 active workflow 若无法从 `master` 读取则 fail-closed；
- 固定 PR 检查名与 runner 边界；
- 外部 Action 的 40 位 SHA 和版本注释；
- `dev` Environment、active workflow 所引用的 secret 名称边界；
- 容器内 smoke、运行镜像身份和 `GITHUB_SHA` 核验标记；
- `master` branch protection 和 required check。

本地 fixture 自测：

```bash
bash tests/test-audit.sh
```

## 不由模板决定的内容

项目自行决定语言、包管理器、测试命令、端口、容器名、镜像名、迁移步骤、服务数量、smoke URL/命令和通知实现。模板只提供替换点，复制后必须结合项目真实行为完成验证。
