# 变更记录

版本号用于纳管项目声明"当前对齐到哪一版基线"。审计器每次运行都会回显版本，
漂移排查时可以据此判断是项目变了还是公共规则变了。

发布流程见 [MAINTENANCE.md](MAINTENANCE.md) 的"发布基线版本"。

## v1.1.0

### 修复

- **release workflow 引用的本地 Action 不再绕过审计。** `.github/actions/**` 之外的本地
  Action 只在被引用时惰性解析，而供应链检查此前跑在解析之前，且 `inspect_release`
  从不计算受控 release 自身的 local action closure。结果是权限最高的 workflow
  可以通过 `./ci/actions/x` 引入未锁定的第三方 Action，审计仍返回 `PASS`；
  prepare job 也能借同样的路径隐藏部署能力。现在所有 `uses:` 引用检查移动到全部
  inspect 之后执行，`inspect_release` 会解析并上报 release 侧 closure，
  prepare 的纯净性判断覆盖其本地 Action。

### 变更

- **区分"基线漂移"与"审计没跑完"。** 新增退出码 `3` 与 `ERROR owner/repo` 前缀、
  `[API_UNAVAILABLE]` 错误码。GitHub 5xx/429/连接失败不再表现为漂移。
- **`gh api` 增加指数退避重试**（4 次尝试，2s/4s/8s，可用
  `BASELINE_AUDIT_RETRY_BASE_SECONDS` 覆盖）。持续不可用的 optional 端点
  （如 `environments/dev`）报 `[API_UNAVAILABLE]`，不再降级成"Environment 缺失"。
- **默认分支参数化。** 新增 `BASELINE_DEFAULT_BRANCH`，默认 `master`。API 路径、
  `github.ref` guard 原子、PR `branches` 与 branch protection 判定全部随之变化，
  基线不再硬编码 `master`。
- **计划任务失败会开 issue。** 漂移 workflow 新增 `notify` job，使用基线仓库自身的
  `GITHUB_TOKEN`（`issues: write`）；只读审计 App 权限不变，issue 正文只放运行链接，
  不回显可能包含 secret 名称的审计输出。
- 审计输出首行回显基线版本与受保护分支。

### 可观测性

- `[WORKFLOW_LIST]` 的"path 不合法"分支改为回显 workflow name 与 path。此前只输出
  一句无主语的错误，维护者无法区分"项目把 workflow 放错位置"与"GitHub 平台内建的
  `dynamic/` workflow 不在仓库里"，也就无从判断该改项目还是改基线。
- 平台内建跳过列表抽出为 `SKIPPED_PLATFORM_WORKFLOWS`；未知 `dynamic/` 路径保持
  fail-closed。

### 测试

- 新增 `tests/unit/`：对表达式解析器、secret 静态可枚举性、`gh api` 重试与分支
  参数化做直接单元测试，不再只靠 fixture 间接覆盖。
- 新增 fixture：`release-local-action-mutable`、`release-local-action-missing`、
  `release-prepare-local-action-deploy`、`api-unavailable`、`main-default-branch`。
- 契约测试改为校验错误码与文档的双向覆盖，不再钉死文档的中文措辞。

## v1.0.0

首个固化版本：PR/release 事件与权限边界、供应链锁定、`dev` Environment 与 secret
边界、`.github/release-safety.yml` 声明式适配与发布/回滚语义校验、`master` branch
protection、根 `AGENTS.md` 的 `## Code Review Rules` 标题校验，以及基于只读 GitHub App
的中央漂移审计。
