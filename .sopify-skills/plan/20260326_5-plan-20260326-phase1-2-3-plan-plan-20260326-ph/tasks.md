---
plan_id: 20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph
feature_key: 5-plan-20260326-phase1-2-3-plan-plan-20260326-ph
level: standard
lifecycle_state: active
knowledge_sync:
  project: review
  background: review
  design: review
  tasks: review
archive_ready: false
---

# 任务清单: 按这 5 条硬约束去正式整理成 plan 边界和任务序列 注意然后可以在20260326_...

## 0. 范围冻结
- [ ] 0.1 将本 plan 明确定位为原 `Plan B1` 的升级版：`global bundle + thin stub/pin + ignore + compatibility`
- [ ] 0.2 显式锁定非目标：不进入 `B2 / B3 / Plan C`，不修改 `.sopify-skills` knowledge contract
- [ ] 0.3 在 `20260326_phase1-2-3-plan` 中同步当前优先级与依赖章节
- [ ] 0.4 冻结本轮允许触达的实现面：`bootstrap_workspace.py / payload.py / validate.py / inspection.py / workspace_preflight.py / hosts/* / runtime/manifest.py / runtime/gate.py / sopify_status.py / sopify_doctor.py / smoke/tests`
- [ ] 0.5 冻结本轮统一解析顺序：`stub -> global bundle -> global manifest -> gate/preload -> legacy fallback`
- [ ] 0.6 冻结本轮统一迁移原则：`stub 优先`、`fallback 可见`、`no_silent_downgrade`

## 0.A 实施顺序约束
- [ ] 0.A.1 先定 stub schema、reason code 与 payload index contract，再动 bootstrap / preflight / diagnostics 实现
- [ ] 0.A.2 `workspace classifier`、`validate`、`inspection` 三处必须同轮收口，禁止只改单点判定器
- [ ] 0.A.3 `host-aware preflight` 与 `payload index` 必须在 `doctor/status/smoke` 之前稳定，否则 diagnostics 会持续漂移
- [ ] 0.A.4 测试、迁移说明、自检脚本放在最后收口，但 reason code 矩阵必须先冻结再补测试

## 0.B | 首次写入许可模型
- [ ] 0.B.1 冻结首次写入许可模型的入口边界：显式强意图命令、`confirm_bootstrap` checkpoint、禁止纯语义自动 bootstrap
- [ ] 0.B.2 冻结强意图白名单与非白名单：明确 `~go / ~go plan / ~go init` 的许可语义，以及 `~compare / 未激活仓库上的 ~go finalize` 默认不触发 bootstrap
- [ ] 0.B.3 冻结语义判定层职责边界：只允许输出结构化 intent proposal，不得直接驱动 `bootstrap / plan scaffold / proposal materialization / workspace write`
- [ ] 0.B.4 冻结首次 auto-bootstrap 生成物边界：默认只写 thin stub，不默认生成 `sopify.config.yaml`
- [ ] 0.B.5 冻结“已激活 workspace”的后续路由语义：继续走 `consult / minimal / adaptive`，不得把激活态等同于“所有请求都强管控”
- [ ] 0.B.6 冻结 host ingress / preflight 的授权位置：首次写入许可必须发生在宿主入口前置决策，不得下沉到 repo-local runtime 内部再确认
- [ ] 0.B.7 冻结 brake layer 的最小覆盖面：`不要改 / 先分析 / 只解释 / 不写文件 / explain-only` 等高确定性表达优先阻断写入意图
- [ ] 0.B.8 冻结 `monorepo / readonly / non-interactive / non-git` 的降级策略与 reason code：不得卡在确认、不得 silent activation、不得静默写到错误 root

## 1. P0 | Bootstrap 与 Ignore 基线
- [ ] 1.1 盘点 bootstrap 当前写路径与 `_REQUIRED_BUNDLE_FILES` 假设，标出必须拆除的 vendored 前提
- [ ] 1.2 定义 ignore mode contract：默认 `.git/info/exclude`、可选 commit-lock `.gitignore`、non-git visible no-op
- [ ] 1.3 设计 `.git/info/exclude` 写入策略：幂等、去重、不覆盖用户自定义条目
- [ ] 1.4 设计 commit-lock mode 的开关来源、写入边界与冲突提示
- [ ] 1.5 设计 non-git repository 的 reason code、可见提示与 fail-open 行为
- [ ] 1.6 明确 bootstrap 输出需要暴露的 observability 字段：ignore_target、ignore_mode、reason_code、workspace_kind

## 2. P1 | Thin Stub Contract
- [ ] 2.1 定义 workspace-local thin stub schema：`schema_version / stub_version / bundle_version / required_capabilities / locator_mode / legacy_fallback / written_by_host`
- [ ] 2.2 定义 thin stub 的最小有效性规则、缺失字段降级规则与 schema evolution 兼容策略
- [ ] 2.3 将 workspace classifier 从“整包文件存在”改为“stub 有效 + global bundle 可解析”
- [ ] 2.4 拆分三层职责：workspace stub 校验、global bundle 校验、legacy vendored 校验
- [ ] 2.5 明确 bootstrap 生成物只写 thin stub，不再复制重型 runtime bundle
- [ ] 2.6 定义 legacy vendored fallback 的进入条件、禁止进入条件与观测字段
- [ ] 2.7 明确 `runtime/manifest.py` 与 installer contract 的边界，避免 stub 与 global bundle manifest 混用

## 3. P2 | Host-Aware Preflight
- [ ] 3.1 为 preflight 入口补 host adapter / host hint 显式输入，不再默认靠目录探测推断宿主
- [ ] 3.2 将 payload root 解析责任收拢到 `installer/hosts/*` 与 host base contract
- [ ] 3.3 移除把 `.codex -> .claude` 固定探测顺序当成最终 payload 选择逻辑的实现
- [ ] 3.4 固化 `stub -> global bundle -> manifest-first gate/preload -> legacy fallback` 的解析顺序
- [ ] 3.5 明确 dual-host 同仓库下的选择规则、冲突提示与 host mismatch reason code
- [ ] 3.6 确保 gate / preload 的入口仍由 resolved global bundle manifest 暴露，而不是宿主侧硬编码

## 4. P3 | Payload Index 与 Diagnostics
- [ ] 4.1 定义 payload-manifest 中的 versioned bundle index schema，与 `bundles/<version>/` 布局对应
- [ ] 4.2 将 `installer/payload.py` 从单 `bundle/` 假设改为按 `bundle_version` 查找目标 bundle
- [ ] 4.3 同步更新 `validate.py`、`inspection.py` 的 bundle discovery 与兼容性判定
- [ ] 4.4 同步更新 `scripts/sopify_status.py`、`scripts/sopify_doctor.py` 的可见输出，展示 stub/global/legacy 解析结果
- [ ] 4.5 同步更新 `scripts/check-install-payload-bundle-smoke.py` 与 distribution 相关校验入口
- [ ] 4.6 在迁移窗口内兼容旧 `bundle/` 结构，但明确标记为 legacy source，不再作为默认目标态
- [ ] 4.7 确保 payload index 升级后，installer / doctor / status / smoke 消费的是同一套 reason code 与 source-kind 词汇

## 5. P4 | Compatibility / Observability / Tests
- [ ] 5.1 定义完整 reason code 矩阵：`stub_selected / stub_invalid / global_bundle_missing / global_bundle_incompatible / legacy_fallback_selected / legacy_fallback_blocked / host_mismatch / non_git_workspace / ignore_written`
- [ ] 5.2 将 reason code 接入 bootstrap、preflight、validate、inspection、status、doctor 的输出面
- [ ] 5.3 补回归测试矩阵：new workspace、legacy vendored workspace、dual-host same repo、non-git workspace、commit-lock mode
- [ ] 5.4 补 smoke 验证矩阵：一次安装、bootstrap、global bundle 解析、fallback visibility、默认入口不变
- [ ] 5.5 更新迁移说明：新仓库、已 bootstrap 仓库、旧 vendored 仓库分别怎么过渡
- [ ] 5.6 更新安装输出与自检脚本，确保用户能看到“当前走的是 stub/global/legacy 哪条路径”

## 5.A 验证分层
- [ ] 5.A.1 单测先覆盖 contract 与判定器：stub validity、payload index、host-aware resolution、fallback gating
- [ ] 5.A.2 集成测试覆盖 bootstrap -> preflight -> gate entry 的主链，不允许只测单函数
- [ ] 5.A.3 smoke 最后验证“一次安装 + 多仓触发 bootstrap + 默认入口不变”

## 6. 总验收门
- [ ] 6.1 新 workspace 默认不再复制重型 vendored runtime bundle
- [ ] 6.2 旧 workspace 仍能运行，且 fallback 可见
- [ ] 6.3 `doctor / status / smoke` 与新 payload index 结构保持一致
- [ ] 6.4 program plan 与 child plan 的优先级、边界、依赖保持一致
- [ ] 6.5 dual-host 同仓库不再靠目录探测顺序选 payload
- [ ] 6.6 git 仓库默认不制造 repo-level 脏 diff；commit-lock mode 行为可解释、可控
- [ ] 6.7 本轮没有把 `A / B2 / C / B3` 的任务或语义偷偷并入 B1
