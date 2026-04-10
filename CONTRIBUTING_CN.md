# 贡献指南

感谢你关注 Sopify 的贡献方式。

## 如何贡献

- 非 trivial 改动请先开 issue，对齐范围和责任边界。
- PR 保持聚焦，尽量做到“一次一个功能或修复”。
- 用户可见行为变更时，同步更新 `README.md` 和 `README.zh-CN.md`。
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

需要以维护者视角验证 thin-stub + selected bundle 接入时，优先使用以下命令：

```bash
# 验证 repo-local 原始输入入口
python3 scripts/sopify_runtime.py --allow-direct-entry \
  --workspace-root /path/to/project "重构数据库层"

# 验证 repo-local runtime gate
python3 scripts/runtime_gate.py enter \
  --workspace-root /path/to/project \
  --request "~go plan 重构数据库层"

# 验证 bundle 完整性
bash scripts/check-runtime-smoke.sh

# 验证“一次安装 + 项目触发 bootstrap + selected bundle 接管”
python3 scripts/check-install-payload-bundle-smoke.py
```

Bundle 规则：

- 全局 payload 位于 `~/.codex/sopify/` 或 `~/.claude/sopify/`
- 工作区内的 `.sopify-runtime/manifest.json` 只作为 thin stub，不再承诺携带 `limits.runtime_gate_entry / limits.preferences_preload_entry`
- 宿主必须结合 workspace stub 与 payload manifest 解析 selected global bundle，再从选中 bundle contract 或等价 preflight contract 发现 helper 入口
- 宿主第一跳统一走 selected bundle 的 `runtime_gate_entry`；只有 repo-local 开发态才直接调用 `scripts/runtime_gate.py enter`
- clarification / decision / develop checkpoint helper 都是内部桥接 helper，不替代默认主入口

### Installer 入口与 Release Asset

当前 installer 入口按受众分层：

- repo-local / 源码安装：

```bash
bash scripts/install-sopify.sh --target codex:zh-CN
python3 scripts/install_sopify.py --target claude:en-US
```

- dev / maintainer 远程入口（`raw/main`，不进 README 首屏）：

```bash
curl -fsSL https://raw.githubusercontent.com/sopify-ai/sopify/main/install.sh | \
  bash -s -- --target codex:zh-CN
```

- public stable 入口（只有在公开 GitHub Release 存在后才启用）：

```bash
curl -fsSL https://github.com/sopify-ai/sopify/releases/latest/download/install.sh | \
  bash -s -- --target codex:zh-CN
```

约定：

- root `install.sh` / `install.ps1` 必须保持 thin wrapper，只负责下载同 ref 的 GitHub source archive 并调用 `scripts/install_sopify.py`
- `main` 分支里的 root 脚本保留 dev 默认值（`SOURCE_CHANNEL=dev`、`SOURCE_REF=main`）
- stable release asset 必须由 root 脚本按 release tag 渲染后上传，不能直接上传 `main` 上的原文件
- 分发层必须继续走 host registry，不允许在 installer 入口里硬编码 `codex` / `claude` 分支；README 只控制当前正式支持面的展示
- `--workspace <path>` 当前只保留给 maintainer / internal prewarm 调试，不属于 B1 默认用户路径；正式路径是先完成全局安装，再在项目里第一次触发 Sopify，由 runtime gate 完成 bootstrap

release asset 渲染 checklist：

```bash
TAG="2026-03-25.142231"
OUT_DIR="$(mktemp -d)"
python3 scripts/render-release-installers.py --release-tag "$TAG" --output-dir "$OUT_DIR"
```

然后：

- 将 `$OUT_DIR/install.sh` 和 `$OUT_DIR/install.ps1` 上传到同 tag 的 GitHub Release
- 在 `releases/latest/download/install.sh` 真正可访问之前，不要切 README 首屏安装命令
- post-release manual smoke 只做维护者校验：确认 latest release asset 存在、stable installer 解析到同 tag，且输出里能看到 `source channel` / `resolved source ref` / `asset name`

## 校验命令

按变更范围选择最小校验集。

Prompt 层与 metadata 同步：

```bash
bash scripts/sync-skills.sh
bash scripts/check-skills-sync.sh
bash scripts/check-version-consistency.sh
python3 scripts/generate-builtin-catalog.py
python3 scripts/check-skill-eval-gate.py
python3 -m unittest discover tests -v
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
python3 -m unittest tests/test_distribution.py tests/test_installer_status_doctor.py -v
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
- `commit-msg` 只有在存在 pre-commit handoff 时，才会追加 `Release-Sync`、`Release-Version`、`Release-Date`
- 命中 Plan A 作用域的提交必须带上 `Context-Checkpoint: A|B|C|D`；hook 只会在 staged files 命中 Plan A runtime/test 面或治理入口资产时强制校验
- 命中 Plan A 作用域的 PR 必须在 `.github/pull_request_template.md` 中填写 `Context-Checkpoint`、`Decision IDs`、`Blocked by`、`Out-of-scope touched`；CI 会同时校验模板和 PR body 元数据

AI attribution 说明：

- 仓库级 AI 协作声明见 [CONTRIBUTORS.md](./CONTRIBUTORS.md)
- 仓库默认不再为 AI 助手追加标准 `Co-authored-by` trailer；除非你手动填写，否则 GitHub contributor attribution 会只归属于人类 commit author
- `SOPIFY_DISABLE_RELEASE_HOOK=1` 会关闭整条 release hook 链；只建议在维护/调试场景使用

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
