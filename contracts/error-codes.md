# 审计错误码参考

审计器逐仓输出结论行与稳定错误码。错误码是本基线的公开接口：漂移处理、告警和
文档都按它定位公共 MUST，因此新增或删除错误码必须同步修改本文，`tests/test-audit.sh`
会双向校验实现与本文完全一致。

## 结论行与退出码

| 结论行 | 含义 |
|---|---|
| `PASS owner/repo` | 该仓库满足全部公共 MUST |
| `FAIL owner/repo` | 检测到基线漂移，逐条错误码列在其后 |
| `ERROR owner/repo` | 审计没能跑完，本次结论不可信，不得当成通过 |

| 退出码 | 含义 |
|---|---|
| `0` | 全部仓库 `PASS` |
| `1` | 至少一个仓库漂移，且没有未完成的审计 |
| `2` | 参数、仓库清单或本地依赖错误 |
| `3` | 至少一个仓库未能完成审计；优先级高于 `1` |

## 审计自身

| 错误码 | 含义 |
|---|---|
| `[ARGUMENT]` | 仓库参数不是 `owner/repo`，或 `BASELINE_DEFAULT_BRANCH` 不是合法分支名 |
| `[API]` | GitHub 响应结构不符合预期，属于可判定的异常 |
| `[API_UNAVAILABLE]` | 重试后仍无法读取 GitHub：网络、5xx/429、响应不是合法 JSON，或 admin 门控字段（如 `allow_auto_merge`）未返回导致无法判定 |

## 仓库与分支

| 错误码 | 含义 |
|---|---|
| `[DEFAULT_BRANCH]` | 仓库 default_branch 不等于基线受保护分支 |
| `[REPOSITORY_MERGE_POLICY]` | `allow_auto_merge` 显式为 `true`。字段缺失表示无法判定，走 `[API_UNAVAILABLE]`，不算漂移 |
| `[BRANCH_PROTECTION]` | strict、PR review、管理员保护、对话解决、force push 或删除保护缺失 |
| `[REQUIRED_CHECK]` | 受保护分支未要求 `PR container validation` |
| `[REQUIRED_CHECK_APP]` | required check 未绑定 GitHub Actions app，或 checks 结构无效 |

## 工作流发现与结构

| 错误码 | 含义 |
|---|---|
| `[WORKFLOW_LIST]` | active workflow 的 path 不在 `.github/workflows/` 下（错误信息回显 name 与 path），或无法从受保护分支读取 |
| `[WORKFLOW_STRUCTURE]` | workflow 或本地 Action 的 YAML 结构不满足最低约束 |
| `[ACTION_TREE]` | recursive tree 被截断或条目结构无效，拒绝不完整审计 |

## 供应链

| 错误码 | 含义 |
|---|---|
| `[ACTION_PIN]` | 外部 Action 未锁定 40 位 commit SHA，或 `docker://` 未锁 sha256 摘要 |
| `[ACTION_VERSION]` | 锁定 SHA 后缺少精确版本注释 |
| `[CHECKOUT_CREDENTIAL]` | `actions/checkout` 未在自身 `with` 中设置 `persist-credentials: false` |
| `[LOCAL_ACTION]` | 本地 Action 路径逃逸、穿过 symlink、无法唯一解析或递归引用 |

## 主 PR workflow

| 错误码 | 含义 |
|---|---|
| `[PR_CHECK_NAME]` | `PR container validation` job 在 active workflow 中不唯一 |
| `[PR_EVENT]` | 主 PR workflow 事件或 `branches` 不精确等于面向受保护分支的 `pull_request` |
| `[PR_PERMISSION]` | 顶层或 job 权限超出 `contents: read` |
| `[PR_RUNNER]` | 未使用 GitHub 托管 `ubuntu-latest` |
| `[PR_ENVIRONMENT]` | PR job 绑定了 Environment |
| `[PR_SECRET]` | 主 PR workflow 或其本地 Action 引用 secret |
| `[PR_DEPLOY]` | 主 PR workflow 或其本地 Action 出现部署能力信号 |

## 辅助 PR workflow

| 错误码 | 含义 |
|---|---|
| `[AUX_PR_PERMISSION]` | 权限超出 CodeQL 例外（`contents: read` + `security-events: write`） |
| `[AUX_PR_RUNNER]` | 使用 self-hosted runner |
| `[AUX_PR_ENVIRONMENT]` | 绑定 Environment |
| `[AUX_PR_SECRET]` | 引用 secret |
| `[AUX_PR_DEPLOY]` | 出现部署能力信号 |

## 发布安全

| 错误码 | 含义 |
|---|---|
| `[RELEASE_MANIFEST]` | manifest schema/引用无效，契约 wrapper 缺失或不可执行，或未声明 job 含特权能力 |
| `[RELEASE_WORKFLOW]` | 受控 release 之外的 workflow 具备发布能力 |
| `[RELEASE_EVENT]` | 发布事件不精确，或 prepare 不是纯校验 job |
| `[RELEASE_PERMISSION]` | release 顶层或 job 权限超出 `contents: read` |
| `[RELEASE_CONCURRENCY]` | 发布与回滚未共享非空串行 concurrency，或 group 按动态量分域 |
| `[RELEASE_FAILURE_STATE]` | 失败被隐藏、cleanup 非 `success()`、failure/finalize guard 无效 |
| `[ROLLBACK_TARGET]` | `workflow_dispatch` 回滚输入不是默认空值的可选 string |
| `[ROLLBACK_GUARD]` | publish/migration/deploy/rollback 的 condition 不满足公共语义 |
| `[ROLLBACK_CAPTURE]` | 发布安全步骤全序无效（capture 必须早于迁移与候选部署等） |
| `[PUBLISH_ENVIRONMENT]` | 发布镜像 job 未绑定 `dev` 且 `deployment: false` |
| `[DEPLOY_ENVIRONMENT]` | 实际部署 job 未绑定真实 `dev` deployment |

## Environment 与 secret

| 错误码 | 含义 |
|---|---|
| `[DEV_ENVIRONMENT]` | 缺少 `dev` Environment，或当前身份无权读取 |
| `[ENV_SECRET_BOUNDARY]` | release 引用的 secret 不在 `dev` Environment |
| `[REPO_SECRET_BOUNDARY]` | repository scope 仍存在 secret 名称 |
| `[SECRET_ENV_BOUNDARY]` | 顶层 env 引用 secret、secret context 无法静态枚举，或使用 `secrets: inherit` |

## 协作规则

| 错误码 | 含义 |
|---|---|
| `[CODE_REVIEW_RULES]` | 根 `AGENTS.md` 缺失、不是普通文件，或缺少精确 `## Code Review Rules` h2 |
