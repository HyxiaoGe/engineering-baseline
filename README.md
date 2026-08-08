# GitHub 工程基线

这是 [HyxiaoGe/engineering-baseline](https://github.com/HyxiaoGe/engineering-baseline) 私有仓库维护的一套可复用 GitHub Actions 与仓库治理基线。它统一跨项目的安全边界和验收证据，不统一项目内部的构建方式。

基线仓库自身不会自动修改纳管项目。`scripts/audit-github-baseline.sh` 只通过 GitHub GET API 读取仓库配置、工作流内容以及 secret **名称**，不会读取或输出 secret 值。

当前纳管仓库记录在 `repositories.txt`。公共规则的变更、Action 升级、新项目接入和漂移处理统一从 [MAINTENANCE.md](MAINTENANCE.md) 进入。

## 接入顺序

1. 从独立 Git worktree 创建变更分支，避免污染长期开发目录。
2. 复制 `templates/AGENTS.md` 到项目根目录，替换全部 `PROJECT_REPLACE` 项并补齐项目内部规则。
3. 复制 `templates/pr-ci.yml` 和 `templates/release.yml`，替换所有 `PROJECT_REPLACE` 项。
4. 在仓库内实现项目自己的 PR 验证、镜像发布、部署、容器内 smoke 和发布收尾脚本。
5. 创建 `dev` Environment，把发布所需 secret 移入该 Environment；确认发布成功后清理 repository-scope secrets。
6. 为 `master` 启用保护规则，要求 GitHub Actions 产生的 `PR container validation`，并保持 strict。
7. 在真实 PR 上先让新检查通过，再原子替换旧 required check；不要先删除旧门禁。
8. 合并后核对运行容器的实际镜像 tag 与 merge SHA，并执行容器内部 smoke。
9. 使用只读审计检查规则漂移。

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

## 自动漂移审计

自动审计只在基线仓库的 `.github/workflows/baseline-drift-audit.yml` 中运行。纳管项目不复制 workflow，也不保存审计凭据。中央任务通过 `actions/create-github-app-token` 创建短期 GitHub App installation token，并在 Action 输入中把 token 精确限制到 `repositories.txt` 对应的四个仓库。

GitHub App 不订阅 webhook 事件，不授予写权限，只配置以下 repository permissions：

- `Administration: read`：读取 `master` branch protection。
- `Actions: read`：列举 active workflows。
- `Contents: read`：读取默认分支 workflow 与本地 Action 内容。
- `Environments: read`：读取 Environment 和 Environment secret 名称元数据。
- `Secrets: read`：读取 repository secret 名称元数据。

基线仓库使用 repository variable `BASELINE_AUDIT_APP_CLIENT_ID` 保存 Client ID，并把私钥作为 `BASELINE_AUDIT_APP_PRIVATE_KEY` 存入 `audit` Environment；workflow 自身只声明 `contents: read`，创建短期令牌时再次显式要求上述五项 `read`。审计器只处理 secret 名称，GitHub API 和脚本都不会读取 secret 值。

接入新项目时必须在同一个基线 PR 中完成三处对齐：

1. 把 `owner/repo` 加入 `repositories.txt`。
2. 把仓库名加入中央 workflow 的 `repositories` 显式列表。
3. 把 GitHub App 安装范围扩展到该仓库。

合并后在基线仓库人工触发一次 `Engineering baseline drift audit`，确认全部仓库输出 `PASS owner/repo`。任何 API 无权读取、清单不一致或结构不完整都会 fail-closed，不能把跳过当成通过。计划任务按 Asia/Shanghai 周一 02:23 运行；GitHub 的 `schedule` 可能延迟，规则正确性以运行结论为准。

## 不由模板决定的内容

项目自行决定语言、包管理器、测试命令、端口、容器名、镜像名、迁移步骤、服务数量、smoke URL/命令和通知实现。模板只提供替换点，复制后必须结合项目真实行为完成验证。
