# 变更提案: B1 升级为全局 Bundle + 本地 Thin Stub/Pin + Ignore/兼容迁移

## 需求背景
当前 `.sopify-runtime/` 仍以 vendored bundle 的形式落到每个项目仓库里，这带来三个已确认的推广阻力：

1. workspace 侵入性偏高
   首次触发后会出现控制面目录，用户体感是“工具代码被打进了项目里”。
2. ignore 策略缺口
   当前 bootstrap 不负责给目标仓库补 ignore，容易把运行时目录直接暴露成脏改动。
3. control-plane 与 knowledge-plane 耦合仍然偏重
   若后续要做 host-aware preflight、dual-host 共存、版本 pin 与 no-silent-downgrade，可复用的重逻辑更适合留在宿主全局 payload 中，而不是继续 per-workspace 复制。

基于前面的设计收口，本轮不再把这件事拆成“先 B1，后中期优化”两期，而是直接把原 `Plan B1` 升级为一次完整的 control-plane decoupling 子 plan：

- 全局保留 versioned runtime bundle 实体
- workspace 只保留极薄的 `.sopify-runtime/manifest.json` thin stub / pin
- bootstrap 同时补齐 ignore、host-aware preflight、legacy fallback 与可观测 reason code

## 核心目标
1. 把重型 runtime bundle 从 workspace 默认体验中移走，保留 workspace-local 的最小控制面入口。
2. 明确 thin stub / global bundle / legacy vendored fallback 的优先级与契约，禁止 silent downgrade。
3. 保持 `manifest-first / runtime gate / preferences preload / handoff-first` 这条控制面主链可审计、可迁移、可回退。
4. 在 `20260326_phase1-2-3-plan` 总纲中同步这条新 child plan 的优先级与依赖关系，避免 program plan 与执行 plan 漂移。

## 变更内容
本 plan 聚焦以下范围：

1. control-plane contract
   - thin stub schema
   - global payload bundle index schema
   - stub-first / global-bundle-second / legacy-fallback-third 的解析顺序
   - 新 reason code 与降级可见性
2. installer / preflight / diagnostics
   - `installer/bootstrap_workspace.py`
   - `runtime/workspace_preflight.py`
   - `installer/payload.py`
   - `installer/validate.py`
   - `installer/inspection.py`
   - `scripts/sopify_status.py`
   - `scripts/sopify_doctor.py`
   - `scripts/check-install-payload-bundle-smoke.py`
3. program sync
   - 现有总纲 `20260326_phase1-2-3-plan` 的优先级 / 依赖章节
   - 相关任务清单同步

## 影响范围
- 模块:
  - `installer/bootstrap_workspace.py`
  - `runtime/workspace_preflight.py`
  - `installer/payload.py`
  - `installer/validate.py`
  - `installer/inspection.py`
  - `installer/hosts/base.py`
  - `installer/hosts/codex.py`
  - `installer/hosts/claude.py`
  - `runtime/gate.py`
  - `runtime/manifest.py`
  - `scripts/sopify_status.py`
  - `scripts/sopify_doctor.py`
  - `scripts/check-install-payload-bundle-smoke.py`
  - `tests/test_installer.py`
  - `tests/test_installer_status_doctor.py`
  - `tests/test_distribution.py`
  - `tests/test_runtime_gate.py`
  - `tests/test_bundle_smoke.py`
- 文件边界:
  - 仅处理 control-plane / installer / diagnostics / compatibility
  - 不改变 `.sopify-skills/plan/blueprint/history` 的知识路径 contract
  - 不进入 `B2 / B3 / Plan C` 的路径或状态机重构

## 非目标
1. 不把 `.sopify-runtime` 并入 `.sopify-skills`
2. 不修改 `plan_path / finalize / history / knowledge_layout` 的现有语义
3. 不实现 Ghost State / Ghost Knowledge / suspend-side-task 行为
4. 不在本轮改写 `ExecutionGate` 的核心字段名或 `gate_status` 值集

## 风险评估
- 风险: 只改 thin stub 字段、不改 bootstrap / validate / inspection 判定器，会导致所有新 workspace 被误判为 `INCOMPATIBLE`
- 缓解: 同时拆分 workspace stub 校验与 global bundle 校验，统一更新 installer / doctor / smoke

- 风险: dual-host 场景继续靠 `.codex -> .claude` 固定探测，可能拿错 payload
- 缓解: preflight 明确切到 host-aware payload 解析，禁止再依赖目录探测顺序做最终判定

- 风险: payload 从单 `bundle/` 改为 versioned index 后，doctor / inspection / validate / smoke 任一链路没跟上都会造成伪失败
- 缓解: 把 payload indexing 与 diagnostics 视为同一原子范围，测试一次性补齐

- 风险: ignore 直接改 repo `.gitignore` 可能制造额外脏 diff
- 缓解: 默认优先 `.git/info/exclude`，只有“提交版本锁”模式才写 `.gitignore`；非 git 仓库显式降级但不阻断

- 风险: legacy vendored fallback 如果不可观测，会让行为漂移难以排查
- 缓解: 新增 `stub 优先 / vendored fallback / no_silent_downgrade` 的 reason code 矩阵，并在 status / doctor / bootstrap 输出中可见

## 评分
- 方案质量: 9/10
- 落地就绪: 8/10
- 评分理由: 范围、硬约束与 program 依赖已经明确，但 installer / diagnostics / dual-host 牵涉面较广，需要一次性收口测试与迁移契约
