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

# 任务清单: B1 文档收口后的实施与验证

## 0. 范围冻结
说明：Section 0 属于前置对齐 / 验证项，用于确保本 plan、program plan 与 `design.md` 已冻结结论保持一致；默认不引入新的产品拍板，勾选标准以文档与实施边界对齐完成为准。
- [x] 0.1 将本 plan 明确定位为原 `Plan B1` 的升级版：`global bundle + thin stub/pin + ignore + compatibility`
- [x] 0.2 显式锁定非目标：不进入 `B2 / B3 / Plan C`，不修改 `.sopify-skills` knowledge contract，不并入 `execution gate / risk classifier` 的 `auth_boundary` 误报修复，不交付 `Migration Utility / prune`
- [x] 0.3 在 `20260326_phase1-2-3-plan` 中同步当前优先级与依赖章节
- [x] 0.4 冻结本轮允许触达的实现面：`bootstrap_workspace.py / payload.py / validate.py / inspection.py / workspace_preflight.py / hosts/* / runtime/manifest.py / runtime/gate.py / runtime/output.py / sopify_status.py / sopify_doctor.py / smoke/tests`
- [x] 0.5 冻结本轮统一解析顺序：`stub -> global bundle -> global manifest -> gate/preload -> legacy fallback`
- [x] 0.6 冻结本轮统一迁移原则：`stub 优先`、`fallback 可见`、`no_silent_downgrade`

## 0.C | 本轮补充冻结
- [x] 0.C.1 明确保持现有认证边界（`option_1`）：本轮不允许修改认证/权限行为
- [x] 0.C.2 明确 B1 只新增 CLI 渲染层：机器契约保持不变，CLI 只做人类可读适配
- [x] 0.C.3 明确 `Migration Utility` 与 `prune` 仅记 `post-B1 backlog`，不纳入本轮 DoD

## 0.H | 前置门禁
- [x] 0.H.1 在本 plan 与 `20260326_phase1-2-3-plan` 中同步 `20260327_hotfix` 为 pre-B1 prerequisite，不把 stale-state Hotfix 并回 B1 实现面
- [x] 0.H.2 将所有触碰 `runtime/state.py / runtime/context_recovery.py / runtime/router.py / runtime/engine.py / runtime/handoff.py / runtime/_models/proposal.py` 协商态一致性的 B1 子任务标记为 `blocked by 20260327_hotfix`
- [x] 0.H.3 将所有依赖 checkpoint / handoff 唯一出口的 `runtime gate / doctor / status / smoke / regression` 验收标记为 `blocked by 20260327_hotfix`
- [x] 0.H.4 明确仅 `bootstrap / thin stub / payload index / manifest / ignore / host adapter` 的纯 filesystem / contract 脚手架可与 Hotfix 并行
- [x] 0.H.5 为并行切片冻结硬边界：不得 `import runtime.state`，不得读取 `.sopify-skills/state/*.json`，不得根据 `current_handoff.json / current_run.json` 推导业务逻辑
- [x] 0.H.6 约定以 `20260327_hotfix` 的 H5 通过作为解除 B1 状态链路阻塞的唯一门
  `20260327_hotfix` 的文档边界、冻结结论与 blocked/parallel-allowed 标签已完成同步；真实 `runtime_gate` smoke 已通过，现可优先恢复 `4.3 / 4.4 / 4.5 / 5.4` 这组此前被门禁压住的切片。

## 0.A 实施顺序约束
- [ ] 0.A.1 以已冻结 stub schema、Primary Outcome Contract、Host Ingress Contract 与 payload index contract 为先，bootstrap / preflight / diagnostics 全部按同一套 contract 落实现
- [ ] 0.A.2 `workspace classifier`、`validate`、`inspection` 三处必须同轮收口，禁止只改单点判定器
- [ ] 0.A.3 `host-aware preflight` 与 `payload index` 必须在 `doctor/status/smoke` 之前稳定，否则 diagnostics 会持续漂移；其中 payload-manifest 的 host-delegated 指针字段名固定为 `active_version`
- [ ] 0.A.4 测试、迁移说明、自检脚本放在最后收口，但 `primary_code` 矩阵与 hint contract 必须先补齐再补测试

## 0.B | 首次写入许可模型
- [ ] 0.B.1 按已冻结结论落首次写入许可模型的入口边界与触发优先级：显式强意图命令、`confirm_bootstrap` checkpoint、禁止纯语义自动 bootstrap，并明确 `~go / ~go plan` 何时可直接落 thin stub
- [x] 0.B.2 按已冻结白名单落宿主入口：明确 `~go / ~go plan / ~go init` 的许可语义，以及 `~compare / 未激活仓库上的 ~go finalize` 默认不触发 bootstrap；其中 `~go init` 只作为合法入口，不阻塞 `B1` 主链交付
- [ ] 0.B.3 按已冻结职责边界收敛语义判定层：只允许输出结构化 intent proposal，不得直接驱动 `bootstrap / plan scaffold / proposal materialization / workspace write`
- [ ] 0.B.4 按已冻结生成物边界落首次 auto-bootstrap：默认只写 thin stub，不默认生成 `sopify.config.yaml`
- [ ] 0.B.5 按已冻结路由语义落实“已激活 workspace”后续行为：继续走 `consult / minimal / adaptive`，不得把激活态等同于“所有请求都强管控”
- [x] 0.B.6 按已冻结授权位置收敛 host ingress / preflight：首次写入许可必须发生在宿主入口前置决策，不得下沉到 repo-local runtime 内部再确认
- [x] 0.B.7 按已冻结规则落实 brake layer 的最小覆盖面：`不要改 / 先分析 / 只解释 / 不写文件 / explain-only` 等高确定性表达优先阻断写入意图
- [x] 0.B.8 按已冻结规则落 `monorepo` 首次激活默认 root 逻辑：`显式 root 指定 > 最近的有效 ancestor marker > 当前 cwd`；`sopify.config.yaml` 不作为上层复用信号；向上 walk 命中的第一个 ancestor marker 只有通过最低有效性才允许复用，若最低有效性失败则立即停止并 `fail-closed` 回退 `cwd`；`repo-root` 级激活必须显式指定
- [x] 0.B.9 按已冻结边界落实 marker 最低有效性：仅用于 root 选择，定义为 `JSON 可解析 + schema_version 存在`，不提前承担 `preflight / validate` 的 stub 健康度校验
- [x] 0.B.10 按已冻结降级策略落 `readonly / non-interactive / non-git / monorepo 歧义` 的 `confirm_bootstrap` 回退条件：不得卡在确认、不得 silent activation、不得静默写到错误 root
  进展记录：part1 已收口 `explicit_allow / blocked_command / no_write_consult / brake_layer_blocked` 四类首次写入前置判定，并把 `activation_root / requested_root / payload_root / host_id` 贯通到 `runtime_gate -> workspace_preflight -> bootstrap helper`。`confirm_bootstrap` checkpoint 与 `readonly / non-interactive` 回退仍留在后续切片，不在本次 part1 收口内。
  进展更新：part2 已补 `root_confirm_required / readonly / non_interactive` 三类 typed 首写阻断，当前通过 `bootstrap helper -> workspace_preflight -> runtime_gate` 稳定返回独立 reason code；`readonly` 场景下 gate receipt 改为 best-effort，避免只读目录再次触发写 receipt 崩溃。
  冻结补充：`non-git` 只在首次激活写入前作为 `confirm_bootstrap` 触发原因之一；确认成功后回到普通成功路径，不抬升为默认主码，只在 warning/evidence 中暴露 `non_git_workspace` 与 `ignore_mode = noop`。
  进展更新：当前已按 B1 最小实现把 `non-git` 首写确认收敛为“`~go / ~go plan` 先阻断并返回 `confirm_bootstrap_required`，显式 `~go init` 或 installer 直装流再继续写入”；写入成功后仍回到 `stub_selected + evidence(non_git_workspace, ignore_mode=noop)`，未引入新的 runtime checkpoint 状态机。
  评审记录：`preflight block` 回合下的 receipt/state fallback 路径目前固定为 `.sopify-skills/...`，作为 pre-config fail-safe contract 明确保留；本轮不追随 custom `plan.directory`，避免 block 分支重新依赖 config。
  评审记录：payload manifest 存在但 JSON 非法/非 object 时，doctor 侧当前仍统一折叠为 `MISSING_REQUIRED_FILE`；已评审为 diagnostics debt，后续在 reason-code matrix 阶段细化，不作为当前阻断项。

## 1. P0 | Bootstrap 与 Ignore 基线
- [ ] 1.1 盘点 bootstrap 当前写路径、ancestor `marker` 探测与 `target_root` 解析逻辑，标出必须拆除的 vendored 前提，并移除 `config` 参与 root 复用的旧分支
- [ ] 1.2 按已冻结 contract 落 `ignore_mode = exclude | gitignore | noop`：git 默认 `.git/info/exclude`，显式 commit-lock 才写 `.gitignore`，non-git visible `noop`
- [ ] 1.3 设计 `.git/info/exclude` 写入策略：优先使用 `BEGIN/END sopify-managed` block 承载 Sopify 条目，best-effort 幂等追加，不覆盖用户自定义条目，不以文件锁或严格去重为前提
- [ ] 1.4 按 bootstrap-time explicit choice 落 commit-lock / `ignore_mode`：写入 thin stub、保持 sticky workspace policy、仅允许显式 re-bootstrap / update 切换；v1 至少对 Sopify 可安全归属的旧 managed block / 已知条目做确定性 reconciliation，超出安全判定范围的残留给出可见提示与手动 remediation，不要求完整 clean/deactivate
- [x] 1.5 设计 non-git repository 的 `confirm_bootstrap` 提示、warning/evidence 暴露与 fail-open 行为；`non_git_workspace` 不作为默认成功/失败主码
  进展记录：当前 non-git 首写在 `bootstrap helper -> workspace_preflight -> runtime_gate` 上统一返回 `confirm_bootstrap_required`，消息固定为“当前目录不是 Git 仓库 / 继续启用后不会自动写入忽略规则”的用户向口径；`~go init` 与 installer 直装流作为显式确认入口放行，写入成功后只通过 `evidence` 暴露 `non_git_workspace + ignore_mode=noop`。
- [ ] 1.6 明确 bootstrap 输出需要暴露的 observability 字段：ignore_target、ignore_mode、reason_code、workspace_kind、target_root、root_resolution_source；并暴露仅覆盖 `thin stub + managed block` 的手动停用路径
  进展记录：当前 bootstrap 输出已稳定暴露 `ignore_mode / ignore_target / reason_code / activation_root / requested_root / root_resolution_source / fallback_reason`，并通过 `evidence` 补出 `non_git_workspace / ignore_mode=noop / root_reuse_ancestor_marker / invalid_ancestor_marker`；`workspace_kind` 命名与手动停用路径仍待后续切片统一。
- [ ] 1.7 明确 `confirm_bootstrap` 文案与 direct-write 提示：至少暴露 `target_root / root_resolution_source / fallback_reason`，且不暗示会自动清理 `.sopify-skills/state/` 或知识库；其中 non-git 写入前确认标题固定为“当前目录不是 Git 仓库”，原因固定为“继续启用后不会自动写入忽略规则。”
  进展记录：当前 helper / gate 已稳定暴露 `activation_root(requested target) / requested_root / root_resolution_source / fallback_reason`，且 non-git 阻断消息已落“当前目录不是 Git 仓库。继续启用后不会自动写入忽略规则。使用 ~go init 确认，或先初始化 Git 后重试。”；若后续需要单独拆 title/reason 字段，再在 host checkpoint contract 中补。
  进展更新：`ROOT_CONFIRM_REQUIRED` 的恢复提示已收口为“默认推荐当前目录、备选仓库根目录、允许手动指定其他目录，并以显式 `activation_root` 重试”；同时保留 root 选择优先于 non-git 确认的顺序，避免在 monorepo 子目录里静默写错 root。

### 当前推荐推进顺序（2026-03-30 评审结论）
1. `4.2 -> 4.6`
2. `2.1 -> 2.2`
3. `3.1 -> 3.6`
4. `2.3 -> 2.7`
5. `4.3-4.5 -> 4.A -> 5.x`

说明：
- `4.2` 先收口 payload bundle 的 `Exact Pin / Host-Delegated` 两态解析；`4.6` 紧随其后把旧 `bundle/` 明确降为 legacy source，避免解析核心继续把兼容路径当默认目标态。
- `2.1 / 2.2` 可以先冻结 thin stub 两态 contract 与降级规则；但 `2.3 / 2.6 / 2.7` 依赖 `3.4 / 3.6` 对统一解析顺序与 resolved global bundle manifest 入口的收口，不建议在 `3.x` 前全量推进。
- `4.3-4.5` 与 `5.x` 继续保持后置；它们消费的是前述解析链的稳定语义，不应反向定义 resolution core。

## 2. P1 | Thin Stub Contract
- [x] 2.1 按已冻结 schema 落 workspace-local thin stub：`schema_version / stub_version / bundle_version / required_capabilities / locator_mode / legacy_fallback / ignore_mode / written_by_host`
  进展记录：`installer/bootstrap_workspace.py` 现会在 workspace manifest 上显式写回 `schema_version / stub_version / bundle_version / required_capabilities / locator_mode / legacy_fallback / ignore_mode / written_by_host` 七项 stub 字段；兼容阶段下仍保留 full manifest 超集，但 stub 合同本身已不再依赖“碰巧沿用 bundle manifest 字段”。
- [x] 2.2 落 thin stub 的最小有效性规则、缺失字段降级规则与 schema evolution 兼容策略，并显式区分“root 选择最低有效性”与“preflight 合同有效性”；至少覆盖 `locator_mode` 缺失视为 `global_first`、`bundle_version` 缺失或 `null` 视为 host-delegated、禁用 semver range / `latest` / 空字符串
  进展记录：`installer/validate.py` 已收紧 stub 校验：`schema_version` 缺失直接 fail、`stub_version` 缺失默认 `1`、`locator_mode` 缺失默认 `global_first`、`bundle_version` 缺失或 `null` 视为 host-delegated、显式空字符串/`latest`/非法版本串全部拒绝。`installer/bootstrap_workspace.py::_marker_has_minimum_validity()` 仍只保持“JSON 可解析 + schema_version 存在”的 root 选择最低有效性，未与 preflight stub 合同有效性混用。
  进展记录：当前已落过渡态实现。workspace `.sopify-runtime/manifest.json` 在保持旧 vendored entry 字段兼容的前提下，开始写入 thin stub 字段，并在 `validate.py / inspection.py / bootstrap_workspace.py` 中统一校验默认值与冲突规则；legacy helper 兼容重试现已改为先保留 `--request` 再降级到 workspace-only，避免首次写入授权语义被错误放宽。完整 `stub-only` 收口仍待 payload index 与入口链切换后继续推进。
  进展更新：`2.3 / 2.4` 已收回上述过渡态限制。当前 workspace health 已改为 `stub 有效 + selected global bundle 可解析` 的 stub-first classifier；legacy runtime 文件只在“workspace 内仍存在 legacy vendored 产物”时单独校验，不再作为 stub-only workspace 的 ready 前提。
- [x] 2.3 将 workspace classifier 从“整包文件存在”改为“stub 有效 + global bundle 可解析”
  进展记录：`installer/bootstrap_workspace.py` 的主 classifier 已不再把 `_REQUIRED_BUNDLE_FILES` 当作 workspace ready 的先决条件，而是先校验 thin stub，再解析 stub 所选的 global bundle；host-delegated 与 exact pin 都通过同一条 selected-bundle 语义落位。
- [x] 2.4 拆分三层职责：root 选择最低有效性、workspace stub 校验、global bundle 校验、legacy vendored 校验
  进展记录：当前已拆成四层责任：`_marker_has_minimum_validity()` 只负责 root 最低有效性；`validate_workspace_stub_manifest()` / bootstrap stub normalizer 负责 workspace stub 合同；selected global bundle 解析与完整性单独校验；legacy vendored runtime 只在产物仍存在时做结构完整性校验。`inspection.py` 与 bootstrap classifier 已共用这套分层语义。
- [x] 2.5 明确 bootstrap 生成物只写 thin stub，不再复制重型 runtime bundle；thin stub 写入采用同目录临时文件 + 原子替换，不引入跨平台文件锁前提
  进展记录：bootstrap 写路径已改为 thin-stub-only，workspace 首次 bootstrap 不再复制重型 runtime bundle，stub 写入也已改为同目录临时文件 + 原子替换；`2.7` 已进一步把 workspace manifest 从过渡态 superset 收成纯 stub contract，因此 `2.5` 在当前 core 分支可一并关闭。
- [x] 2.6 落 legacy vendored fallback 决策表与观测字段：`global_only + missing/incompatible -> no fallback`；`global_first + legacy_fallback=true + missing/incompatible -> visible legacy fallback`；禁止 silent downgrade
  进展记录：bootstrap/classifier 已按显式决策表收口 `global_only / global_first / legacy_fallback` 组合；`global_first + legacy_fallback=true + global fail + legacy complete` 现稳定返回 `READY + LEGACY_FALLBACK_SELECTED`，`legacy absent/broken` 继续 fail-close 并沿用原始 global reason code。
- [x] 2.7 明确 `runtime/manifest.py` 与 installer contract 的边界，避免 stub 与 global bundle manifest 混用
  进展记录：bootstrap 现只写 workspace thin stub 字段，不再把 `capabilities / limits / default_entry` 等 bundle contract 混入 `.sopify-runtime/manifest.json`；`status/doctor` 的 capability 校验也已改为正常路径读取 selected global bundle manifest，仅在 `LEGACY_FALLBACK_SELECTED` 时继续读取 legacy workspace manifest，保持向后兼容。

## 3. P2 | Host-Aware Preflight
- [x] 3.1 为 preflight 入口补正式 ingress contract：`activation_root / host_id / payload_root` 为必填输入，`requested_root` 为可选 observability 输入且推荐宿主在可确定时提供；不再默认靠目录探测推断宿主
  进展记录：`activation_root / host_id / payload_root / requested_root` 已稳定贯通到 `scripts/runtime_gate.py -> runtime/gate.py -> runtime/workspace_preflight.py`；preflight 入口现以显式 ingress 字段与 host-aware payload 解析为主，`requested_root` 继续只做 observability。更细的字段级 `violations[]` 与 CLI fail-closed 渲染仍留在后续 diagnostics 层，不在本轮 overbuild。
- [x] 3.2 将 payload root 解析责任收拢到 `installer/hosts/*` 与 host base contract
  进展记录：`runtime/workspace_preflight.py` 已移除自带 `.codex/.claude` 路径表，改为通过 `installer.hosts` registry 解析 host payload root 与候选 manifest。
- [x] 3.3 移除把 `.codex -> .claude` 固定探测顺序当成最终 payload 选择逻辑的实现
  进展记录：host 未显式指定时，当前选择规则已改为 `SOPIFY_PAYLOAD_MANIFEST > 当前宿主环境 > 单一已安装 payload > 多候选 fail-closed`；不再依赖 `.codex -> .claude` 固定顺序。
- [x] 3.4 固化 `stub -> global bundle -> manifest-first gate/preload -> legacy fallback` 的解析顺序
  进展记录：preflight 现统一通过 `installer.validate` 的 payload bundle resolution 解析 `bundle_manifest_path / global_bundle_root`，与 payload index 的 `active_version / legacy layout` 语义保持一致；request-preserving helper compatibility fallback 继续保留，不额外引入新的降级分叉。
- [x] 3.5 明确 dual-host 同仓库下的选择规则、冲突提示与 `host_mismatch / ingress_contract_invalid` 的产出边界，并让 monorepo root 复用结果进入同一 observability 词汇表
  进展记录：dual-host 选择规则已先按最小 contract 收口到 preflight 核心：显式 `host_id/payload_root` 继续保留 escape hatch，当前宿主可判定时优先选择匹配 host，无法判定且存在多个已安装 payload 时 fail-closed；typed `host_mismatch / ingress_contract_invalid` 的用户可见渲染继续后置到 `4.A/5.x`，避免在 preflight core 过度设计。
- [x] 3.6 确保 gate / preload 的入口仍由 resolved global bundle manifest 暴露，而不是宿主侧硬编码
  进展记录：preflight 现从 resolved global bundle manifest 暴露 `runtime_gate_entry / preferences_preload_entry`；versioned/current bundle 走 manifest-first 暴露，legacy fixture 缺失 `limits.*` 时继续按兼容路径放行，不阻断现有 helper fallback smoke。

## 4. P3 | Payload Index 与 Diagnostics
- [x] 4.1 定义 payload-manifest 中的 versioned bundle index schema，与 `bundles/<version>/` 布局对应，并包含 host-delegated 模式所需的唯一 `active_version` 指针；其值格式必须与 thin stub 的 `bundle_version` Exact Pin 一致
- [x] 4.2 将 `installer/payload.py` 从单 `bundle/` 假设改为按 `bundle_version` 两态查找目标 bundle：Exact Pin 精确命中，Host-Delegated 读取唯一 `active_version` 指针
  进展记录：已收紧 `installer/payload.py / installer/validate.py` 的 payload bundle 解析：versioned layout 下 Host-Delegated 只认 `active_version`，缺失时 fail-closed 为 `GLOBAL_INDEX_CORRUPTED`；Exact Pin 继续精确命中 `bundles/<version>/manifest.json`，不再把顶层 `bundle_version` 当作 versioned host-delegated 指针兜底。
- [x] 4.3 同步更新 `validate.py`、`inspection.py` 的 bundle discovery 与兼容性判定
- [x] 4.4 同步更新 `scripts/sopify_status.py`、`scripts/sopify_doctor.py` 的可见输出，展示 stub/global/legacy 解析结果，并针对 `global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected` 提供不同的 actionable hint
  进展记录：`status/doctor` 现统一消费 `installer.inspection` 的 payload bundle resolution；文本输出会显式展示 `source_kind + reason_code`，并按 `GLOBAL_BUNDLE_MISSING / GLOBAL_BUNDLE_INCOMPATIBLE / GLOBAL_INDEX_CORRUPTED / LEGACY_FALLBACK_SELECTED` 输出不同 remediation hint。
- [x] 4.5 同步更新 `scripts/check-install-payload-bundle-smoke.py` 与 distribution 相关校验入口
  进展记录：distribution install 输出与独立 `check-install-payload-bundle-smoke.py` 现统一暴露 `payload_bundle` 诊断对象；smoke 会显式校验 `global_active + PAYLOAD_BUNDLE_READY`，distribution 也会打印同一套 source/reason contract。
- [x] 4.6 在迁移窗口内兼容旧 `bundle/` 结构，但明确标记为 legacy source，不再作为默认目标态
  进展记录：已保留 legacy `bundle/manifest.json` 的显式 exact-pin 兼容路径，但仅在无 `bundles_dir` 的旧布局下生效；`status / doctor` 新增回归覆盖 versioned layout 缺失 `active_version` 时 fail-closed，而旧 `bundle/` 继续以 `legacy_layout / LEGACY_FALLBACK_SELECTED` 暴露为兼容来源。
- [x] 4.7 确保 payload index 升级后，installer / doctor / status / smoke 消费的是同一套 reason code 与 source-kind 词汇
  进展记录：已冻结并接通 `PAYLOAD_BUNDLE_READY / GLOBAL_BUNDLE_MISSING / GLOBAL_BUNDLE_INCOMPATIBLE / GLOBAL_INDEX_CORRUPTED / LEGACY_FALLBACK_SELECTED` 与 `global_active / legacy_layout / unresolved` 词汇，installer、status、doctor、distribution、smoke 与对应单测已共用同一 contract。
  进展更新：公开 prompt、`CONTRIBUTING_CN.md` 与 `scripts/check-runtime-smoke.sh` 已同步改成 thin-stub + selected global bundle / workspace preflight 模型；bundle manifest 继续承载 `limits.*`，workspace stub 显式保持无 helper 入口，smoke 改为同时校验这两层职责不混淆。

## 4.A | CLI Rendering Layer
- [ ] 4.A.1 冻结 CLI 渲染适配层边界：只消费 `primary_code + action_level + evidence` 与 `violations[]`，不反向定义新的机器字段
- [ ] 4.A.2 为 `ingress_contract_invalid` 设计终端友好渲染：把 `activation_root / host_id / payload_root` 的 violation 渲染成字段级高亮与明确 remediation，不直接裸打嵌套 JSON 错误树
- [ ] 4.A.3 为 `global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected` 定义分码渲染文案，保证 `status / doctor / CLI 面板` 行为一致
- [ ] 4.A.4 保留原始结构化 contract 的 debug / `--json` 出口，避免 CLI 友好文案反向污染 IDE / 自动化消费路径
- [ ] 4.A.5 为终端渲染补示例或快照，覆盖“普通用户视图”和“调试原始视图”两层输出

## 5. P4 | Compatibility / Observability / Tests
说明：`5.1 / 5.2` 是 `5.3 / 5.A.*` 的前置物；未补齐默认主码集合、diagnostic-only 集合与 hint contract 前，不得启动 P4 测试。
- [x] 5.1 冻结结果码分层：`default primary codes = stub_selected / stub_invalid / global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected / host_mismatch / ingress_contract_invalid / root_confirm_required / readonly / non_interactive`；`diagnostic-only identifiers（仅经 evidence / warning surface 暴露，不作为默认首屏主码） = non_git_workspace / ignore_written / root_reuse_ancestor_marker / invalid_ancestor_marker / legacy_fallback_blocked`
  进展记录：文档矩阵已冻结；当前实现已把 `stub_selected / stub_invalid / global bundle failures / legacy_fallback_selected / root_confirm_required / readonly / non_interactive` 接入 bootstrap / preflight / inspection 的主结果面，并把 `non_git_workspace / root_reuse_ancestor_marker / invalid_ancestor_marker` 压回 evidence。
- [ ] 5.2 将 `default primary codes + action_level + typed evidence` 接入 bootstrap、preflight、validate、inspection、status、doctor 与 CLI 渲染层的输出面，并为 `diagnostic-only identifiers` 冻结 evidence / warning surface 与 reason-code-specific 的用户可见 hint 分类；不新增新的稳定机器字段
  进展记录：当前已接入 `bootstrap / workspace_preflight / runtime_gate / inspection / doctor tests` 的主结果与 evidence 语义，并把 `stub_invalid / global bundle failures` 的 recommendation 文案收成更直接的用户口径；`action_level` 统一命名与剩余 `status / doctor` 终端文案细化仍待后续切片补齐。
- [ ] 5.3 补回归测试矩阵：new workspace、legacy vendored workspace、dual-host same repo、non-git workspace、commit-lock mode、monorepo nearest-ancestor-marker reuse、monorepo invalid-nearest-ancestor-marker fail-closed、monorepo explicit-root override；其中 dual-host same repo 只断言 `host_mismatch + typed evidence`，不绑定提示文案模板；non-git workspace 断言“写入前触发 `confirm_bootstrap` + 写入后只在 evidence / warning 中暴露 `non_git_workspace + ignore_mode=noop`”，不要求其成为默认首屏主码
  进展记录：当前已补 non-git 行的两段式回归：`~go plan` 在非 Git 首写时阻断并返回 `confirm_bootstrap_required`，`~go init` 成功后回到 `stub_selected + non_git_workspace/ignore_mode=noop`；其余 dual-host / commit-lock 等行仍待补齐。
- [ ] 5.4 补 smoke 验证矩阵：一次安装、bootstrap、global bundle 解析、fallback visibility、默认入口不变
- [ ] 5.5 更新迁移说明：新仓库、已 bootstrap 仓库、旧 vendored 仓库分别怎么过渡，并确保迁移说明与 `doctor / status` 的 actionable hint 一致；本轮仅补可见性与说明，不提供一键迁移器
- [ ] 5.6 更新安装输出与自检脚本，确保用户能看到“当前走的是 stub/global/legacy 哪条路径”
  进展记录：已冻结 installer surface 收口方向：`--workspace` 保留 internal / maintainer prewarm，不作为 B1 默认用户路径；若要正式支持 monorepo `activation_root` / root confirm UX，放到 post-B1 单独立项。
- [x] 5.7 已确定移出本轮：installer 三入口 Python 最低版本 preflight 不纳入当前 B1 主线与 `feature/plan-b1-bootstrap-policy` 分支策略；后续如需推进，单独立项并补对应回归

## 5.A 验证分层
- [ ] 5.A.1 单测先覆盖 contract 与判定器：stub validity、payload index、host-aware resolution、fallback gating、`ingress_contract_invalid` 的 `violations[]` 顺序与短路规则，以及 CLI 渲染层的字段级映射；dual-host 相关断言只覆盖 `host_mismatch + typed evidence`，不覆盖提示文案模板；non-git 相关断言只覆盖写入前 `confirm_bootstrap` 触发原因与写入后 `evidence / warning` 暴露，不把 `non_git_workspace` 绑定成默认主码
  进展记录：本轮已补 `stub_selected / stub_invalid` 语义回归、legacy fallback 主链、`root_confirm_required / readonly / non_interactive` 首写阻断、以及 non-git 的“写入前 `confirm_bootstrap_required` / 写入后只走 `evidence`”双段式断言；`ingress_contract_invalid` 的 `violations[]` 和 dual-host `host_mismatch` 仍待后续切片补齐。
- [ ] 5.A.2 集成测试覆盖 bootstrap -> preflight -> gate entry 的主链，不允许只测单函数
- [ ] 5.A.3 smoke 最后验证“一次安装 + 多仓触发 bootstrap + 默认入口不变”

## 6. 总验收门
- [ ] 6.1 新 workspace 默认不再复制重型 vendored runtime bundle
- [ ] 6.2 旧 workspace 仍能运行，且 fallback 可见
- [ ] 6.3 `doctor / status / smoke` 与新 payload index 结构保持一致
- [ ] 6.4 program plan 与 child plan 的优先级、边界、依赖保持一致
- [ ] 6.5 dual-host 同仓库不再靠目录探测顺序选 payload
- [ ] 6.6 git 仓库默认不制造 repo-level 脏 diff；commit-lock mode 行为可解释、可控
- [ ] 6.7 monorepo 首次激活默认不静默爬升到 `repo-root`；仅在最近的有效 ancestor marker 命中时复用上层，命中无效 ancestor marker 时立即 `fail-closed` 回退 `cwd`
- [ ] 6.8 本轮没有把 `A / B2 / C / B3` 的任务或语义，或 `execution gate / risk classifier` 的误报修复偷偷并入 B1

## 7. Post-B1 Backlog
- Direct switch preparation checklist
  - host first-hop 改造完成，不再依赖 workspace-local scripts 作为默认入口
  - `no workspace scripts` smoke 全绿
  - 回滚验证通过
  - 仅在上述门槛都满足后，才允许把 `stub-only` 从 non-ready 提升为 ready
- Migration Utility
  - 目标是为旧 vendored workspace 提供可确认的一键升级路径，但不属于当前 B1 交付门
- Bundle prune
  - 目标是清理未被任何 thin stub 引用的历史 `bundles/<version>/`，但不属于当前 B1 交付门
- Installer Python preflight
  - 原 `5.7`；覆盖 `install.sh / scripts/install-sopify.sh / scripts/install_sopify.py` 的 Python 最低版本 preflight 与最小回归
  - 不纳入当前 B1 主线与 `feature/plan-b1-bootstrap-policy` 分支策略，后续单独立项处理
