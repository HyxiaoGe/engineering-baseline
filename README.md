# GitHub 工程基线

这是 [HyxiaoGe/engineering-baseline](https://github.com/HyxiaoGe/engineering-baseline) 公开仓库维护的一套可复用 GitHub Actions 与仓库治理基线。它统一跨项目的安全边界和验收证据，不统一项目内部的构建方式。

基线仓库自身不会自动修改纳管项目。`scripts/audit-github-baseline.sh` 只通过 GitHub GET API 读取仓库配置、工作流内容以及 secret **名称**，不会读取或输出 secret 值。

当前纳管仓库记录在 `repositories.txt`，版本变更记录在 [CHANGELOG.md](CHANGELOG.md)。

## 文档导航

公共 MUST 只在 `contracts/` 下定义，本文与维护手册不复述规则，只负责入口与操作步骤。

| 文档 | 作用 |
|---|---|
| [contracts/ci-cd-baseline.md](contracts/ci-cd-baseline.md) | CI/CD 公共契约：事件、权限、供应链、发布安全、分支保护、secret 边界 |
| [contracts/codex-code-review.md](contracts/codex-code-review.md) | 官方 Codex Code Review 治理契约：接入、审查内容、finding 收敛、合并边界 |
| [contracts/error-codes.md](contracts/error-codes.md) | 审计结论行、退出码与全部稳定错误码 |
| [MAINTENANCE.md](MAINTENANCE.md) | 日常审计、新项目接入、规则变更、Action 升级、漂移处理 |

## 接入顺序

1. 从独立 Git worktree 创建变更分支，避免污染长期开发目录。
2. 复制 `templates/AGENTS.md` 到项目根目录，替换全部 `PROJECT_REPLACE` 项并补齐项目内部规则，保留精确标题 `## Code Review Rules`。
3. 在官方 GitHub/Codex 设置中启用 Code Review 与 `Automatic reviews`；规则只决定审查重点，不负责触发，人工兜底使用 `@codex review`。
4. 保持仓库 Auto-merge 关闭；分支自动删除按项目真实分支模型配置。边界见[官方 Codex Code Review 治理契约](contracts/codex-code-review.md) §5。
5. 复制 `templates/pr-ci.yml`、`templates/release.yml`、`templates/release-safety.yml` 和 `templates/release-safety-contract.sh`；将后两份分别安装为 `.github/release-safety.yml` 与 `.github/scripts/release-safety-contract.sh`，保持 wrapper 为 `100755`，再替换所有 `PROJECT_REPLACE` 项。
6. 在仓库内实现项目自己的 PR 验证、镜像发布、向前迁移、部署、自动恢复、容器内 smoke、成功后镜像清理和发布收尾脚本；由固定 wrapper 调用项目语言或容器内的可执行契约测试，并让 manifest 声明 wrapper 与 PR 稳定步骤 ID。
7. 创建 `dev` Environment，把发布所需 secret 移入该 Environment；确认发布成功后清理 repository-scope secrets。
8. 为受保护分支启用保护规则，要求 GitHub Actions 产生的 `PR container validation`，并保持 strict。
9. 在真实 PR 上先让新检查通过，再原子替换旧 required check；不要先删除旧门禁。
10. 合并后核对运行容器的 image ref、内容 ID 与 `DEPLOY_TARGET_SHA`，并执行容器内部 smoke。
11. 使用只读审计检查规则漂移。

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

脚本逐仓输出 `PASS`、`FAIL` 或 `ERROR`。**`FAIL` 表示基线漂移，`ERROR` 表示审计本身没跑完、结论不可信**；两者的退出码不同，不得把后者当成通过。全部结论行、退出码与错误码见 [contracts/error-codes.md](contracts/error-codes.md)。

### 可配置项

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `BASELINE_DEFAULT_BRANCH` | `master` | 基线受保护分支名；同时决定 API 读取的 ref、`github.ref` guard 原子与 PR `branches` 判定 |
| `BASELINE_AUDIT_RETRY_BASE_SECONDS` | `2` | `gh api` 瞬时失败的退避基数，共尝试 4 次 |

### 审计覆盖范围

审计只验证可由结构化 YAML 与仓库配置可靠判断的高层约束，逐条 MUST 见[公共契约](contracts/ci-cd-baseline.md)：

- active PR/release workflow 的事件、权限、runner、Environment 与 secret 边界；
- 受控 release 之外发现任一发布能力即 fail-closed；GitHub 内建的 `dynamic/dependabot/update-graph` 明确跳过，其他 active workflow 读不到即 fail-closed；
- 外部 Action 的 40 位 SHA、版本注释、`docker://` 内容摘要，以及 workflow 与本地 Action 闭包中的全部 `uses:` 引用；
- `.github/release-safety.yml` 的 schema、语义 job/step 引用、依赖、condition 映射与步骤全序，以及中央独立验证的 publish/deploy/finalize 公共语义；
- 项目发布安全契约 wrapper 是 mode `100755` 的普通文件，且被唯一的 `PR container validation` job 以单行 `run` 精确调用；
- `dev` Environment 与 repo/env secret 名称边界；
- 受保护分支的 branch protection 与 required check；
- 仓库关闭 Auto-merge；根 `AGENTS.md` 是普通文件且含精确 `## Code Review Rules` h2。

中央审计明确不解释任意 shell 的控制流，也不尝试从注释、`echo`、here-doc、字符串或脚本名证明 ref/内容 ID 比对、容器内 smoke、回滚命令及实际 `DEPLOY_TARGET_SHA`。它也不抓取官方页面或私有接口来判断 Automatic reviews 设置、模型审查质量、在途 Review 或审查轮次预算。这些事实分别由项目可执行契约测试、真实发布验收和真实 PR 时间线负责。

PR workflow 无法触达生产的**结构性**保证来自四条硬约束：`contents: read` 顶层权限、不引用 secret、不绑定 Environment、只用 GitHub 托管 runner。命令关键字扫描（`[PR_DEPLOY]`）是这四条之上的次级网，它可以被项目脚本内部的命令绕过，因此只作为补充信号，不作为主要保证。

模板只是一种可复制 profile，`.github/release-safety.yml` 才是每个项目拓扑的声明式适配层。

### 本地自测

```bash
bash tests/test-audit.sh
```

包含 fixture 端到端用例、表达式解析器与 API 重试的单元测试（`tests/unit/`），以及模板、契约骨架和错误码参考的一致性校验。

## 自动漂移审计

自动审计只在基线仓库的 `.github/workflows/baseline-drift-audit.yml` 中运行。纳管项目不复制 workflow，也不保存审计凭据。中央任务通过 `actions/create-github-app-token` 创建短期 GitHub App installation token，并在 Action 输入中把 token 精确限制到 `repositories.txt` 对应的仓库。

只读 GitHub App `Engineering Baseline Auditor` 的权限清单与私钥存放规则见 [MAINTENANCE.md](MAINTENANCE.md) 的"发布基线版本"。审计器只处理 secret 名称，GitHub API 和脚本都不会读取 secret 值。

计划任务失败时，独立的 `notify` job 会开或更新一个 issue。该 job 只使用基线仓库自身的 `GITHUB_TOKEN`（`issues: write`），审计 App 保持零写权限；issue 正文只放运行链接，不回显可能包含 secret 名称的审计输出。

接入新项目时必须在同一个基线 PR 中完成三处对齐：

1. 把 `owner/repo` 加入 `repositories.txt`。
2. 把仓库名加入中央 workflow 的 `repositories` 显式列表。
3. 把 GitHub App 安装范围扩展到该仓库。

合并后在基线仓库人工触发一次 `Engineering baseline drift audit`，确认全部仓库输出 `PASS owner/repo`。任何 API 无权读取、清单不一致或结构不完整都会 fail-closed，不能把跳过当成通过。计划任务按 Asia/Shanghai 周一 02:23 运行；GitHub 的 `schedule` 可能延迟，规则正确性以运行结论为准。

## 不由模板决定的内容

项目自行决定语言、包管理器、测试命令、job/step ID、是否需要 prepare/finalize、端口、容器名、镜像名、迁移步骤、服务数量、smoke URL/命令和通知实现。项目必须按真实拓扑维护 `.github/release-safety.yml`，并结合真实行为完成验证。

数据库迁移必须采用 expand/contract，禁止自动执行 `alembic downgrade`；镜像恢复只恢复应用运行态，不宣称回滚数据库。捕获的旧 ref 必须是受管 `IMAGE_NAME:<40 位小写 SHA>`，内容 ID 必须是 `sha256:<64 位小写十六进制>`。首次部署没有可捕获的旧镜像时默认 fail-closed。

手动回滚不使用第二份 workflow：在现有 release 的 `workflow_dispatch` 填写 40 位小写 `rollback_sha` 和非空原因。同一 deploy job 使用该值作为 `DEPLOY_TARGET_SHA`，跳过 publish 和迁移，完成身份与容器内 smoke；留空两个输入则仍补跑当前 `GITHUB_SHA`。
