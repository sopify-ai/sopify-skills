# 贡献指南

感谢你关注 Sopify 的贡献方式。

## 如何贡献

- 非 trivial 改动请先开 issue，对齐范围和责任边界。
- PR 保持聚焦，尽量做到“一次一个功能或修复”。
- 用户可见行为变更时，同步更新 `README.md` 和 `README_EN.md`。
- 用户可见行为或维护规则变化时，手动更新 `CHANGELOG.md`。

## Prompt 层与 Skill Authoring

- `Codex/Skills/{CN,EN}` 是 prompt-layer 真源。
- `Claude/Skills/{CN,EN}` 是宿主镜像层，不应独立手工维护。
- `runtime/builtin_skill_packages/*/skill.yaml` 是 builtin machine metadata 真源。
- Skill package 变更时，参考 [Codex/Skills/CN/skills/sopify/](./Codex/Skills/CN/skills/sopify/) / [Codex/Skills/EN/skills/sopify/](./Codex/Skills/EN/skills/sopify/) 下各自的 `SKILL.md`。

关键约束：

- route 绑定优先使用 `supports_routes`
- `skill.yaml` 统一经 `runtime/skill_schema.py` 校验
- `tools / disallowed_tools / allowed_paths / requires_network` 当前仍以声明字段为主，除非 runtime 显式强制
- builtin catalog 通过脚本再生成，不手改生成产物

## Runtime Bundle 与宿主接入

需要以维护者视角控制 vendored runtime bundle 时，使用以下命令：

```bash
# 将 runtime 资产同步到目标工作区
bash scripts/sync-runtime-assets.sh /path/to/project

# 验证目标工作区的原始输入入口
python3 /path/to/project/.sopify-runtime/scripts/sopify_runtime.py \
  --workspace-root /path/to/project "重构数据库层"

# 可选：在目标工作区运行便携测试与 smoke
python3 -m unittest /path/to/project/.sopify-runtime/tests/test_runtime.py
bash /path/to/project/.sopify-runtime/scripts/check-runtime-smoke.sh
```

Bundle 规则：

- 全局 payload 位于 `~/.codex/sopify/` 或 `~/.claude/sopify/`
- 宿主必须优先读取 `.sopify-runtime/manifest.json`
- 宿主第一跳统一走 `.sopify-runtime/scripts/runtime_gate.py enter`
- clarification / decision / develop checkpoint helper 都是内部桥接 helper，不替代默认主入口

## 校验命令

按变更范围选择最小校验集。

Prompt 层与 metadata 同步：

```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest tests.test_runtime -v
```

仓库内 runtime 验证：

```bash
python3 scripts/sopify_runtime.py "重构数据库层"
python3 scripts/runtime_gate.py enter --workspace-root . --request "重构数据库层"
python3 scripts/sopify_runtime.py "~go plan 重构数据库层"
python3 scripts/sopify_runtime.py "~go finalize"
python3 scripts/go_plan_runtime.py "重构数据库层"
bash scripts/check-runtime-smoke.sh
```

文档与发布校验：

```bash
python3 scripts/check-readme-links.py
python3 -m unittest tests/test_release_hooks.py -v
bash scripts/check-version-consistency.sh
```

## Release Hook 与 CHANGELOG

仓库内置了 `.githooks/pre-commit` 与 `commit-msg` 的联动自动化。

每个 clone 只需启用一次：

```bash
git config core.hooksPath .githooks
```

行为摘要：

- `pre-commit` 会先运行 `scripts/release-preflight.sh`，再运行 `scripts/release-sync.sh`
- release-managed 文件会在检查通过后自动回到同一个 commit
- 当 `CHANGELOG.md -> [Unreleased]` 为空时，`release-sync` 会根据当前 staged files 自动生成分组草稿
- `commit-msg` 只会根据 pre-commit handoff 追加 `Release-Sync`、`Release-Version`、`Release-Date`

常用环境变量：

- `SOPIFY_DISABLE_RELEASE_HOOK=1`
- `SOPIFY_SKIP_RELEASE_PREFLIGHT=1`
- `SOPIFY_AUTO_DRAFT_CHANGELOG=0`
- `SOPIFY_RELEASE_HOOK_DRY_RUN=1`
- `SOPIFY_FORCE_RELEASE_SYNC=1`

## 许可说明

提交贡献即表示你同意按目标文件对应的许可分发你的改动：

- 代码与配置：Apache 2.0
- 文档：CC BY 4.0
