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
- 任一项目新增或修改 PR、发布、部署 workflow；
- required check、branch protection、Environment 或 secret scope 发生变化；
- 新项目首次接入，以及接入后的首个 master 发布完成后。

## 新项目接入

1. 在独立 worktree 中复制并按项目实际情况改造 `templates/` 下的 PR 与 release 模板。
2. 通过真实 PR 证明 `PR container validation` 成功，随后原子迁移 master required check。
3. 通过一次 master 发布证明 Environment-only secret、镜像身份和容器内 smoke。
4. 将 `owner/repo` 追加到 `repositories.txt`。
5. 运行 fixture 测试和维护清单 live 审计；两者都成功后才算纳入基线。

## 修改公共规则

1. 先在 `contracts/ci-cd-baseline.md` 明确公共 MUST 与项目扩展点，避免把单个项目细节升格为通用规则。
2. 为审计器补充能够复现旧实现缺口的失败 fixture，取得 RED 后再修改实现。
3. 同步模板、已知 Action SHA/版本映射和 README。
4. 执行：

   ```bash
   bash tests/test-audit.sh
   ./scripts/audit-maintained-repositories.sh
   ```

5. 检查四仓真实 PR、master 发布和运行环境证据；只读审计不能替代这些门禁。

## Action 升级

- 只接受上游官方 release 对应的完整 40 位 commit SHA。
- 同时更新模板、审计器 `KNOWN_ACTIONS`、契约中的版本表和相关 fixture。
- 通过真实 PR 验证后再合并；不得先改 required check 或回退为浮动 tag。

## 漂移处理

- 先依据稳定错误码定位公共 MUST，例如 `[ACTION_PIN]`、`[REQUIRED_CHECK_APP]`、`[SECRET_ENV_BOUNDARY]`。
- 所有持久修复都从目标仓库的独立分支经 PR 进入 master，不直接修改 dev 服务器代码。
- 修复后重新执行目标仓库 PR、master 发布、部署身份/健康验收和全清单审计。
- 新的通用缺口必须沉淀为 fixture；只修项目而不增强审计器，会留下相同漂移再次发生的入口。
