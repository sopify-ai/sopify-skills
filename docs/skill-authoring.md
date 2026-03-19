# Skill Authoring 规范（Sopify）

本文档定义 Sopify skill package 的目录契约、`skill.yaml` 机器字段、权限边界和发布前检查流程。

## 1. 适用范围

适用于以下技能目录：

- `Codex/Skills/{CN,EN}/skills/sopify/*`（prompt-layer 真源）
- `Claude/Skills/{CN,EN}/skills/sopify/*`（由同步脚本镜像）
- `runtime/builtin_skill_packages/*`（runtime 机器事实源）

## 2. Skill Package 目录契约

当前仓库实现（逻辑 package）：

```text
Codex/Skills/{CN,EN}/skills/sopify/<skill>/
├── SKILL.md
├── references/
├── assets/
└── scripts/

runtime/builtin_skill_packages/<skill>/
└── skill.yaml
```

职责边界：

1. `SKILL.md`：入口文档，只保留触发条件、流程骨架、边界与导航。
2. `skill.yaml`：机器元数据（路由、权限、宿主支持、runtime entry），当前落在 `runtime/builtin_skill_packages/*`。
3. `references/`：长规则、背景知识、策略说明。
4. `assets/`：模板、输出样式、示例片段。
5. `scripts/`：确定性逻辑（可重复、可测试、无主观推断）。

反模式：

- 把长模板和大段规则直接塞回 `SKILL.md`。
- 在 `SKILL.md` 里重复 `skill.yaml` 中已有机器字段。
- 在 `scripts/` 中写依赖交互猜测的非确定逻辑。

## 3. `skill.yaml` 字段规范

字段来源与校验以 `runtime/skill_schema.py` 为准。

### 3.1 常用字段

```yaml
schema_version: "1"
id: analyze
mode: workflow # advisory | workflow | runtime
names:
  zh-CN: analyze
  en-US: analyze
descriptions:
  zh-CN: 需求分析入口
  en-US: Analyze entry
handoff_kind: analysis
contract_version: "1"
supports_routes:
  - workflow
  - plan_only
triggers:
  - "~compare"
tools:
  - read
disallowed_tools:
  - write
allowed_paths:
  - .
requires_network: false
host_support:
  - codex
  - claude
permission_mode: default # default | host | runtime | dual
```

### 3.2 权限字段语义

1. `tools`：允许工具集合。
2. `disallowed_tools`：显式禁止工具集合。
3. `allowed_paths`：允许访问路径前缀。
4. `requires_network`：是否依赖网络。
5. `host_support`：允许执行的宿主集合。
6. `permission_mode`：权限执行责任模式。

说明：当前 runtime 只对 `skill.yaml` schema、`host_support`、runtime `permission_mode` 执行 fail-closed；`tools / disallowed_tools / allowed_paths / requires_network` 仍是声明字段，尚未进入 runtime 强执行。

## 4. 与 runtime 契约对齐

### 4.1 声明式 route->skill 绑定

- 通过 `supports_routes` 声明目标路由。
- resolver 优先声明式绑定，缺失时才走 legacy fallback。
- 参考实现：`runtime/skill_resolver.py`。

### 4.2 生成链（Source-of-Truth）

```text
runtime/builtin_skill_packages/*/skill.yaml
  -> normalize/validate
  -> scripts/generate-builtin-catalog.py
  -> runtime/builtin_catalog.generated.json
  -> runtime/builtin_catalog.py (优先消费 generated)
```

说明：`builtin_catalog.generated.json` 是生成产物，不手写维护。

### 4.3 fail-closed 规则

1. `skill.yaml` 校验失败：registry 跳过该 skill。
2. `host_support` 不匹配：registry 跳过或拒绝执行该 skill。
3. runtime skill 的 `permission_mode` 非法：执行期抛错并阻断。
4. `tools / disallowed_tools / allowed_paths / requires_network` 当前不做 runtime 强执行，不应在文档中描述为“已强执”。
5. 已落地的约束边界不允许静默放宽。

## 5. `SKILL.md` 入口文档模板

建议结构：

1. 何时激活（路由/场景）
2. 执行骨架（3-6 步）
3. 资源导航（references/assets/scripts）
4. 确定性逻辑入口（脚本调用示例）
5. 边界（不负责什么）

试点参考：

- `Codex/Skills/CN/skills/sopify/analyze/`
- `Codex/Skills/CN/skills/sopify/design/`
- `Codex/Skills/CN/skills/sopify/develop/`
- `Codex/Skills/EN/skills/sopify/analyze/`
- `Codex/Skills/EN/skills/sopify/design/`
- `Codex/Skills/EN/skills/sopify/develop/`

## 6. 变更流程（维护者）

1. 在 `Codex/Skills/{CN,EN}` 编辑 prompt-layer 真源。
2. 在 `runtime/builtin_skill_packages/*/skill.yaml` 编辑 builtin machine metadata 真源。
3. 同步到 Claude 镜像：`bash scripts/sync-skills.sh`。
4. 校验镜像一致性：`bash scripts/check-skills-sync.sh`。
5. 校验版本一致性：`bash scripts/check-version-consistency.sh`。
6. 生成 catalog：`python3 scripts/generate-builtin-catalog.py`。
7. 运行 skill eval gate：`python3 scripts/check-skill-eval-gate.py`。
8. 回归 runtime 测试：`python3 -m unittest tests.test_runtime -v`。

## 7. 合并前最小检查单

- [ ] `SKILL.md` 已收敛为入口文档
- [ ] 长规则已迁移 `references/`
- [ ] 模板/示例已迁移 `assets/`
- [ ] 确定性逻辑已进入 `scripts/`
- [ ] `skill.yaml` 通过 schema 校验
- [ ] catalog 生成产物已更新
- [ ] sync + check + eval + tests 全通过

## 8. 收口追溯（5.4）

本轮 `skill standards refactor` 的长期收口资料：

1. 专项蓝图：`../.sopify-skills/blueprint/skill-standards-refactor.md`
2. Eval baseline：`../evals/skill_eval_baseline.json`
3. Eval SLO：`../evals/skill_eval_slo.json`
