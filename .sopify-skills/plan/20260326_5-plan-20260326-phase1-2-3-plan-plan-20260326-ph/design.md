# 技术设计: B1 升级为全局 Bundle + 本地 Thin Stub/Pin + Ignore/兼容迁移 + CLI 渲染收口

## 技术方案
- 核心目标: 将原 `Plan B1` 从“延迟物化”升级为完整的 control-plane decoupling 方案，收口 global bundle、thin stub、bootstrap ignore、host-aware preflight 与 legacy compatibility
- 设计结论:
  - workspace 继续保留 `.sopify-runtime/manifest.json` 作为本地控制面入口，但不再复制重型 runtime 代码
  - 重型 Python runtime 与相关 manifest-first control-plane 逻辑保留在宿主全局 payload 中，以 versioned bundle store 管理
  - `.sopify-skills/` 继续只承载知识与状态，不承担全局 bundle locator 的 first-hop 入口职责
  - 机器侧继续以结构化 contract 为唯一事实源，CLI 只新增人类可读渲染层，不回改机器字段

## 本轮补充冻结
1. 保持现有认证边界（`option_1`）
   - 本轮不允许把 B1 扩展成认证/权限行为改造；若现有 `auth_boundary` 风险提示存在误报，也不在本轮顺手修 classifier

2. 只把 CLI 渲染层纳入 B1
   - 本轮新增范围仅覆盖 `status / doctor / CLI 面板` 对结构化错误树的友好渲染
   - 不改变 `primary_code / action_level / evidence / violations[]` 的机器契约

3. `Migration Utility` 与 `prune` 进入 post-B1 backlog
   - B1 只承诺迁移可见性、提示与说明
   - B1 不承诺一键升级器，也不承诺完整 `deactivate / clean / prune`

4. installer Python 最低版本 preflight 移出本轮
   - 原 `5.7` 的 installer 三入口 Python 最低版本 preflight 不纳入当前 B1 主线与 `feature/plan-b1-bootstrap-policy` 分支策略
   - 若后续需要推进，单独立项并补对应回归；本轮不借道扩大 `bootstrap policy + code matrix + CLI surface` 的实现面

## Part1 收口状态
- 已落地：
  - 首次写入授权前移到 host ingress / workspace preflight，`~go / ~go plan / ~go init` 与 `~compare / ~go finalize / ~go exec` 的首写语义已落白名单/黑名单
  - brake layer 已覆盖 `不要改 / 先分析 / 只解释 / 不写文件 / explain-only / read-only` 等高确定性 no-write 表达
  - `activation_root / requested_root / host_id / payload_root` 已贯通 `runtime_gate -> gate -> workspace_preflight`，monorepo root 选择与 invalid ancestor marker fail-closed 已进入实现与回归
  - thin-stub compatibility phase 已补齐 request-preserving legacy helper fallback，避免只是不支持 `--host-id` 的旧 helper 把非写入请求错误降级为默认授权
- 仍未在 part1 完成：
  - `confirm_bootstrap` checkpoint 与 `readonly / non-interactive` 回退
  - 真正的 `stub-only` workspace ready-path
  - payload index 与 versioned global bundle discovery

## 前置门禁 | 状态机 Hotfix
- `20260327_hotfix` 现已作为本 plan 的前置门禁单独立项，负责修复 stale-state、ghost proposal、checkpoint resolver 分裂与 contradictory handoff
- 本 plan 不吸收 `runtime/state.py / runtime/context_recovery.py / runtime/router.py / runtime/engine.py / runtime/handoff.py / runtime/_models/proposal.py` 的协商态一致性修复
- B1 当前被阻塞的切片包括：
  - 任何依赖 runtime checkpoint 唯一出口的 `gate / handoff / doctor / status / smoke / regression`
  - 任何需要重新定义 `proposal / clarification / decision` 作用域与 provenance 的实现
- B1 当前允许与 Hotfix 并行的切片包括：
  - `bootstrap / thin stub / payload index / manifest / ignore / host adapter` 的纯 filesystem 与 contract 脚手架
- 并行硬边界：
  - 不得 `import runtime.state`
  - 不得读取 `.sopify-skills/state/*.json`
  - 不得根据 `current_handoff.json / current_run.json` 推导业务逻辑

## 前置产品决策 | 首次写入许可模型
- 本条款是 `Plan B1` 的前置产品决策，优先级高于 `bootstrap / thin stub / host-aware preflight / payload index` 的具体实现拆分
- 本条款只冻结一件事：`首次何时允许向 workspace 写入 Sopify 控制面资产`

### 决策结论
1. 默认禁止纯语义自动 bootstrap
   - 自然语言复杂度识别、任务规模判断、语义路由结果，均不得直接触发首次写入 workspace

2. 首次写入只允许发生在两类入口
   - 显式强意图命令：`~go` / `~go plan` / `~go init`
   - 宿主先展示 `confirm_bootstrap` 类 checkpoint，且用户明确确认
   - `~go init` 在本轮只冻结为合法 bootstrap 白名单入口，不阻塞 `B1` 主链交付；交互式引导问答流留作后续增强

3. 显式强意图命令与 `confirm_bootstrap` 的优先级必须固定
   - `~go` / `~go plan` 在 `interactive + writable + target_root 无歧义 + 未命中 brake layer` 时，可直接写入 thin stub
   - 仅当 `monorepo root` 存在歧义、workspace 不可写、处于 `non-interactive / non-git` 场景、或命中 brake layer 时，宿主才应回退到 `confirm_bootstrap`
   - `non-git` 仅作为首次激活写入前的 `confirm_bootstrap` 触发原因之一；确认成功后回到普通成功路径，不单独抬为默认成功/失败主码，只在 warning/evidence 中暴露 `non_git_workspace` 与 `ignore_mode = noop`

4. 语义判定层只负责提议，不负责授权
   - 语义层只能输出结构化 intent proposal
   - 不得直接驱动 `bootstrap / plan scaffold / proposal materialization / workspace write`

5. 首次 auto-bootstrap 默认只写 thin stub
   - 默认只落 `.sopify-runtime/manifest.json` 等最小控制面资产
   - 不默认生成 `sopify.config.yaml`

6. 已激活 workspace 不等于强制进入 planning
   - “已激活”只表示该项目允许 Sopify control-plane 介入
   - 后续请求仍按 `consult / minimal / adaptive` 正常路由，不得把激活态等同于“所有请求都强管控”

### 硬约束
1. `~compare`、`~go finalize` 默认不视为首次 bootstrap 的强意图入口
2. agent / 局部语境识别只可用于三分流：`no_write_consult`、`ask_confirm`、`explicit_allow`
3. 首次写入授权必须发生在 host ingress / preflight 侧，不允许把“先 bootstrap 再确认”下沉到 repo-local runtime
4. 必须保留窄口 brake layer，对 `不要改 / 先分析 / 只解释 / 不写文件 / explain-only` 这类高确定性表达优先阻断写入意图
5. `monorepo` 首次激活的默认 root 规则必须固定
   - root 选择优先级固定为：`显式 root 指定 > 最近的有效 ancestor marker > 当前 cwd`
   - `sopify.config.yaml` 只影响运行时行为，不作为上层 root 复用信号
   - 未显式指定 root 时，仅 `.sopify-runtime/manifest.json` 可作为 ancestor marker；向上 walk 时命中的第一个 ancestor marker 通过最低有效性才允许复用
   - 若最近的 ancestor marker 不满足最低有效性，必须立即停止向上 walk 并 `fail-closed` 回退到当前 `cwd`，不得继续静默上爬到更远祖先
   - 需要 `repo-root` 级激活时，必须显式指定
6. marker 的最低有效性只用于 root 选择，不替代 preflight 的 stub 健康度校验
   - 最低有效性 = `JSON 可解析 + schema_version 字段存在`
   - `schema_version` 值域、其他字段完整性与 bundle 兼容性仍由 `preflight / validate` 负责
7. `non-interactive / readonly / non-git / monorepo` 场景必须有确定性降级，不得卡在确认、不得 silent activation、不得静默写到错误 root
   - 其中 `non-git` 的确定性降级必须分层：写入前触发 `confirm_bootstrap`，写入后仅在 warning/evidence 中可见，不额外生成默认结果主码
8. 所有授权路径都必须产出稳定 reason code，禁止 silent bootstrap，禁止 silent downgrade

### 非目标
- 不在本轮引入“纯全局 auto-bootstrap 开关”作为主模型
- 不在本轮把 agent 判定扩展为自由式路由裁决器
- 不在本轮把 `B2 / B3 / Plan C / Plan A` 语义并入本决策
- 不在本轮修 `execution gate / risk classifier` 对“写入授权”与“业务认证/权限边界”的 `auth_boundary` 误报
- 不在本轮交付 `Migration Utility`
- 不在本轮交付历史 bundle `prune`

### 与实施顺序的关系
1. 先冻结本条款，再进入 `P0-P4` 的实现拆分
2. 触碰 runtime 状态链路与协商恢复的 B1 子任务必须等待 `20260327_hotfix` 的 H5 通过后再继续
3. `thin stub / ignore / host-aware preflight / payload index` 的纯 filesystem / manifest 脚手架可与 Hotfix 并行，但必须服从上面的并行硬边界
4. `B2` 只继承该授权模型，不得在后续全局 state 改造中重新打开“纯语义自动激活”路径

## 目标态

### 1. 全局 Bundle 实体
宿主全局 payload 从单一 `bundle/` 布局升级为 versioned bundle store，典型形态为：

```text
<host-home>/<host-dir>/sopify/
├── payload-manifest.json
├── helpers/
│   └── bootstrap_workspace.py
└── bundles/
    ├── <version-a>/
    └── <version-b>/
```

约束：
- 不在 thin stub 中硬编码 `.codex` 或 `.claude` 的具体绝对路径
- payload root 由 host adapter 决定，再从 payload index 解析 bundle location
- 旧 `bundle/` 布局在迁移窗口内可作为 legacy source，但不是长期主路径

### 2. 本地 Thin Stub / Pin
workspace-local `.sopify-runtime/manifest.json` 只保留最小控制面字段，例如：

- `schema_version`
- `stub_version`
- `bundle_version`
- `required_capabilities`
- `locator_mode`
- `legacy_fallback`
- `ignore_mode`
- `written_by_host`

约束：
- thin stub 只表达“当前项目要找哪一版、要求哪些最低能力、是否允许 legacy fallback，以及 workspace ignore 策略”，不承担 payload root 推导
- `locator_mode` 值域固定为 `global_first | global_only`；默认值与缺失值都视为 `global_first`
- `bundle_version` 只允许两态：
  - `Exact Pin`：显式版本字符串，按精确版本匹配；不支持 semver range、`latest` 或空字符串
  - `Host-Delegated`：字段缺失或 `null`；由 payload-manifest 的唯一 `active_version` 指针决定目标 bundle；`active_version` 的值格式必须与 `bundle_version` 的 `Exact Pin` 保持一致，并直接对应 `bundles/<version>/` 目录名；若该指针缺失或损坏，独立产出 `global_index_corrupted`
- `required_capabilities` 当前闭合集合固定为 `runtime_gate | preferences_preload`
- `legacy_fallback` 默认 `false`；只在 `locator_mode = global_first` 下有意义；任何 fallback 都必须可见，不得 silent downgrade
- `locator_mode = global_only` 与 `legacy_fallback = true` 的组合视为 stub contract 冲突，按 invalid 处理
- `ignore_mode` 值域固定为 `exclude | gitignore | noop`；由 bootstrap 时的显式选择写入 thin stub，并作为 sticky workspace policy 持久化
- git 仓库默认 `ignore_mode = exclude`；显式 commit-lock 选择才允许 `ignore_mode = gitignore`；non-git workspace 记录为 `ignore_mode = noop`
- `ignore_mode` 的后续切换必须通过显式 re-bootstrap / update 流程，并对旧模式遗留做确定性 reconciliation
- thin stub 不是 `.sopify-skills` 的一部分
- thin stub 写入采用“同目录临时文件 + 原子替换”，不把跨平台文件锁作为 `B1` 前提

实现记录（2026-03-30）：
- `installer/bootstrap_workspace.py` 已在 workspace manifest 上显式写回上述 stub 七字段；当前 compatibility phase 仍保留 full manifest 超集，但 stub 合同字段不再依赖 bundle manifest 的隐式遗留值。
- `installer/validate.py` 已把 stub 合同有效性与 marker 最低有效性保持分层：marker 复用仍只要求 `JSON 可解析 + schema_version 存在`，而 stub 校验额外要求 `schema_version` 有效、`stub_version` 可归一、`locator_mode` 缺失默认 `global_first`、`bundle_version` 仅允许 `Exact Pin` 或 `Host-Delegated(missing/null)`，显式空字符串 / `latest` / 非法版本串全部拒绝。

### 3. 解析顺序
新 preflight 顺序应固定为：

1. 读取 workspace-local thin stub
2. 由当前 host adapter 解析 payload root
3. 从 payload index 定位目标 global bundle
4. 读取 global bundle manifest
5. 由该 manifest 暴露的 `runtime_gate_entry / preferences_preload_entry` 执行控制面主链
6. 仅当 thin stub 缺失或声明允许时，才进入 legacy vendored fallback

关键分支固定为：
- `locator_mode = global_only + global_bundle_missing` -> `global_bundle_missing`，不得 fallback
- `locator_mode = global_only + global_bundle_incompatible` -> `global_bundle_incompatible`，不得 fallback
- `locator_mode = global_first + legacy_fallback = true + global_bundle_missing` -> `legacy_fallback_selected`，且必须可见
- `locator_mode = global_first + legacy_fallback = true + global_bundle_incompatible` -> `legacy_fallback_selected`，且必须可见

### 2026-03-30 实现记录 | 3.1 / 3.6
- `runtime/workspace_preflight.py` 已改为通过 `installer.hosts` registry 与 `installer.validate` 的统一 payload bundle resolution 收口 preflight 链路，不再内置 `.codex -> .claude` 固定探测顺序，也不再自带一套独立 bundle-manifest 选择逻辑。
- host 未显式指定时，当前选择规则已收口为 `SOPIFY_PAYLOAD_MANIFEST > 当前宿主环境(CODEX_/CLAUDE_) > 单一已安装 payload > 多候选 fail-closed`；显式 `payload_root` 继续作为 escape hatch，避免 dual-host 场景再次回到目录顺序猜测。
- preflight 现显式暴露 resolved `bundle_manifest_path / global_bundle_root / runtime_gate_entry / preferences_preload_entry`，从而把 gate/preload 入口绑定到 resolved global bundle manifest；legacy helper/bundle fixture 缺失 `limits.*` 时仅跳过入口暴露，不阻断 compatibility fallback。
- 本次仍保持最小实现：typed `host_mismatch / ingress_contract_invalid` 用户可见 surface 与字段级 violation 渲染继续留在 `4.A / 5.x`，不在 preflight core 额外扩散机器字段。

### 4. Ignore 默认值 / commit-lock
默认策略：

1. `ignore_mode` 由 bootstrap-time explicit choice 决定并写入 thin stub；它不是每次运行都要重复携带的 CLI flag，也不依赖首次可能不存在的配置文件
2. git 仓库默认写 `.git/info/exclude`（`ignore_mode = exclude`）
3. 仅在显式 commit-lock 选择时才更新 `.gitignore`（`ignore_mode = gitignore`）
4. 非 git 仓库在首次激活写入前作为 `confirm_bootstrap` 的触发原因之一；确认并写入成功后给出可见但不阻断的 warning/evidence，并记录为 `ignore_mode = noop`，但不额外抬升为默认结果主码
5. `.git/info/exclude` 使用 managed block（`BEGIN/END sopify-managed`）承载 Sopify 条目，按 best-effort 幂等追加；不以严格去重或文件锁为前提
6. 若后续切换 `ignore_mode`，必须通过显式 re-bootstrap / update 流程完成，并对 Sopify 可安全归属的旧模式条目做确定性处理；超出安全判定范围的残留给出可见提示与手动 remediation，不得静默遗留

## 五条硬约束
以下约束是本 plan 的强门禁，不是可选优化：

1. thin stub 不能只改字段，不改判定器
   - `bootstrap_workspace.py`、`validate.py`、`inspection.py` 必须同步拆分 workspace stub 校验与 global bundle 校验

2. dual-host 解析必须显式 host-aware
   - 不能继续依赖 `.codex -> .claude` 固定探测顺序作为最终 payload 选择逻辑

3. payload 索引化必须牵动全链路
   - `payload.py`、`validate.py`、`inspection.py`、`doctor/status`、smoke 与安装输出必须一起升级

4. ignore 策略默认优先 `.git/info/exclude`
   - `.gitignore` 只在“提交版本锁”模式才写
   - 非 git 仓库必须定义可见降级行为
   - `.git/info/exclude` 采用 managed block，允许 best-effort 幂等追加，不要求文件锁或严格去重

5. 兼容迁移必须有可观测 reason code
   - `stub 优先`
   - `legacy vendored fallback 次之`
   - `no_silent_downgrade`
   - `doctor / status` 必须基于具体 reason code 给出不同的 actionable hint，不得把 `missing / incompatible / legacy` 合并成同一句提示

### 2026-03-30 实现记录 | 4.2 / 4.6
- versioned payload layout 下，Host-Delegated 已明确只消费 `active_version`；顶层 `bundle_version` 不再承担 versioned 指针兜底语义，缺失 `active_version` 时按 index corruption fail-closed。
- legacy `bundle/` 兼容仍保留，但只作为 legacy source：无 `bundles_dir` 时才允许走 `bundle/manifest.json`，且 `status / doctor` 继续以 `legacy_layout / LEGACY_FALLBACK_SELECTED` 暴露，不回升为默认目标态。

## 入口契约冻结结论
以下入口契约已在本 plan 内冻结，不再作为实现前待拍板项：

1. Primary Outcome Contract
   - 对外只暴露 `primary_code + action_level + evidence`，不对消费端暴露 stage events 列表
   - `action_level` 与 `primary_code` 分离；消费侧仅可基于这三者做分支、渲染与测试断言
   - `global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected` 保持独立 `primary_code`，以支持不同的 actionable hint
   - `legacy_fallback_selected` 不得 silent downgrade；若允许继续执行，必须带有可见性或确认语义
   - `stub_invalid` 保持独立 `primary_code`；其 remediation 指向 workspace-local `.sopify-runtime/manifest.json`，不得与全局 bundle 问题混桶
   - `legacy_fallback_blocked` 不进入默认结果 `primary_code` 集合；仅作为对应 global failure outcome 的 `evidence` / doctor / status 补充诊断暴露
   - `message_hint` 仅作 `debug/unstable` 辅助文本；消费侧不得依赖它驱动逻辑、渲染用户提示或编写稳定测试断言

2. Host Ingress Contract
   - 正式 ingress 核心签名固定为：`activation_root + host_id + payload_root`
   - `host_id` 只用于审计、诊断与冲突提示，不参与路径推导或 payload 选择
   - `requested_root` 为可选 observability 字段；宿主在可确定时应提供，但它不得进入 `activation_root` 派生、根选择、ancestor marker walk 或其他控制面决策
   - dual-host same repo 场景的稳定机器事实只冻结到 `host_mismatch + typed evidence`；用户可见冲突提示文案不进入稳定 contract，也不作为测试断言对象
   - debug wrapper 仅作为 repo-local / 调试路径的 implementation note；不构成 public core contract，也不得重新引入主路径目录猜测

3. Ingress Validation Contract
   - `ingress_contract_invalid` 为独立 `primary_code`，且 `action_level` 唯一合法值是 `fail_closed`
   - `ingress_contract_invalid` 的合法产出方仅限 ingress 层：正式 ingress validator 与 debug wrapper 的归一化步骤；`preflight / validate / inspection / doctor / status` 一律禁止产出该码
   - `evidence.violations[]` 是 ingress 参数错误的唯一稳定结构；固定顺序为 `activation_root -> host_id -> payload_root`
   - 每个参数最多只产出一条 violation；单参数内的短路顺序固定为 `missing -> invalid_value -> invalid_path -> not_found -> unreadable`
   - `violations[].error_kind` 值集固定为 `missing | invalid_value | invalid_path | not_found | unreadable`
   - 当目标存在但不可作为目录使用时，`error_kind = not_found`，并可通过 `actual_kind = file | broken_symlink | other` 提供附加诊断；symlink 最终指向目录时视为合法

4. Result-Code Layering
   - `default primary codes` 只保留会改变默认 `next_step` 的结果：`stub_selected / stub_invalid / global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected / host_mismatch / ingress_contract_invalid / root_confirm_required / readonly / non_interactive`
   - `diagnostic-only identifiers` 只经 `evidence` 与 CLI warning surface 暴露，不新增新的稳定机器字段：`non_git_workspace / ignore_written / root_reuse_ancestor_marker / invalid_ancestor_marker / legacy_fallback_blocked`
   - `non_git_workspace` 不是默认成功主码，也不是默认失败主码；它只在首次激活写入前作为 `confirm_bootstrap` 触发原因，写入后只留在 warning/evidence，并同时暴露 `ignore_mode = noop`
   - `confirm_bootstrap` 的触发原因不得与结果主码混用：写入前由 checkpoint reason / evidence 表达，写入后成功路径回到 `stub_selected`

## CLI 渲染层补充冻结
1. 渲染层职责
   - CLI 渲染层只消费稳定机器事实：`primary_code + action_level + evidence`，以及 `ingress_contract_invalid` 下的 `violations[]`
   - 渲染层不得反向定义新的机器字段，也不得让消费端依赖自然语言文案做逻辑分支

2. 输出分层
   - IDE / host bridge / 调试脚本继续消费结构化 contract
   - `sopify status`、`sopify doctor` 与终端面板新增友好渲染：先给一行结论，再给字段级定位与 remediation
   - 原始 JSON 仅保留给 `--json / debug` 或等价调试视图，不作为普通终端默认主视图

3. `ingress_contract_invalid` 的渲染要求
   - 必须把 `violations[]` 渲染成字段级高亮，而不是直接打印嵌套错误树
   - 至少覆盖 `activation_root / host_id / payload_root` 三类字段，并对 `invalid_path / not_found / unreadable` 产出不同的友好提示
   - 终端文案可以更友好，但底层仍以 `violations[]` 顺序与 `error_kind` 作为唯一稳定事实

4. 现有 reason code 的渲染要求
   - `global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected` 继续保持独立 `primary_code`
   - CLI 提示必须按 `primary_code` 区分 remediation，不得重新合并成一个泛化报错

5. 边界
   - CLI 渲染层不改变 runtime gate、execution gate、decision checkpoint 的机器契约
   - CLI 渲染层不改变认证/权限边界，也不触发新的决策分叉

## 本轮已收口
- 入口契约、Thin Stub Contract 与 commit-lock / `ignore_mode` 已在本 plan 内冻结；后续剩余工作仅为文档一致性补齐、实现落位与测试/迁移验证，不再新增产品拍板项

## 实施边界

### P0 | Bootstrap 与 Ignore 基线
- bootstrap 增加 ignore writer
- 默认写 `.git/info/exclude`
- 按已冻结 `ignore_mode` contract 落 `.gitignore` 行为、切换流程与旧产物 reconciliation
- 定义 non-git repository 的降级输出
- thin stub 写入采用“同目录临时文件 + 原子替换”
- `.git/info/exclude` 使用 managed block，按 best-effort 幂等追加 Sopify 条目
- bootstrap / status 可见输出提供 control-plane 手动停用提示，但范围只覆盖 thin stub 与 managed block，不涉及 `.sopify-skills/state/` 或知识库

### P1 | Thin Stub Contract
- 按已冻结 Thin Stub Contract 落 schema / validator / 默认值判定
- 改写 workspace classifier，不再要求 `_REQUIRED_BUNDLE_FILES`
- 分离 workspace stub 校验与 global bundle 校验

### 2026-03-30 实现记录 | 2.3 / 2.4
- `installer/bootstrap_workspace.py` 的 workspace classifier 已从“workspace runtime 文件完整”切到“thin stub 有效 + selected global bundle 可解析”的 stub-first 语义；`_REQUIRED_BUNDLE_FILES` 不再作为 stub-only workspace ready 的硬前提。
- classifier 现拆成四层：root 最低有效性继续只由 `_marker_has_minimum_validity()` 负责；workspace stub 合同由 stub normalizer / `validate_workspace_stub_manifest()` 负责；selected global bundle 单独做 capabilities + required files 校验；legacy vendored runtime 只在 workspace 内仍存在 legacy 产物时单独验完整性。
- `installer/inspection.py` 已对齐这套分层：workspace health 先按 stub 选择对应的 global bundle，再决定 ready/fail；stub-only workspace 在 global bundle 可解析时视为 ready，而 legacy runtime 的半损坏仍保持 fail-closed。

### P2 | Host-Aware Preflight
- 让 preflight 显式接收 `activation_root / host_id / payload_root`，并可选接收 `requested_root` 作为 observability 字段
- 删除把 `.codex` / `.claude` 固定探测顺序当成最终判定依据的逻辑
- 建立 `stub -> global bundle -> manifest-first gate/preload -> legacy fallback` 的统一顺序
- 固化 `Primary Outcome Contract + Ingress Validation Contract`，确保入口错误与运行态错误不再混桶

### P3 | Payload Index 与 Diagnostics
- payload 从单 `bundle/` 迁移到 versioned bundle store
- `validate / inspection / doctor / status / smoke / distribution` 同步升级
- 迁移窗口兼容旧 `bundle/` 结构，但输出明确 reason code
- `doctor / status` 针对 `global_bundle_missing / global_bundle_incompatible / global_index_corrupted / legacy_fallback_selected` 提供不同的 actionable hint
- CLI 渲染层针对 `ingress_contract_invalid` 与上述 `primary_code` 补人类可读提示，但不改变底层结构化 contract

### P4 | Compatibility / Tests / Migration
- 为 stub-first 与 legacy fallback 补 reason code 矩阵
- 为 dual-host / old workspace / non-git 仓库补回归测试
- 同步总纲与迁移说明（仅限可见性/说明；不包含一键迁移器）
- installer `--workspace` 本轮仅保留 internal / maintainer prewarm，不作为 B1 正式用户入口；若后续要正式支持 monorepo `activation_root` / root confirm UX，需在 B1 后单独立项

## 验收门
1. 新 workspace bootstrap 后只落 thin stub，不再复制整包 runtime
2. dual-host 同仓库场景下，payload 选择由 host-aware contract 决定，不再靠目录探测顺序兜底
3. payload index 升级后，`validate / inspection / doctor / status / smoke` 全部通过
4. git 仓库默认不制造 repo-level 脏 diff；commit-lock mode 行为可控
5. legacy vendored workspace 仍可运行，但 fallback 状态在 bootstrap / doctor / status 中可见
6. `plan/blueprint/history` 与 `plan_path / finalize / knowledge_layout` 的语义保持不变

## 分支拆分、分批合并与单次 Stable 发布策略
- 默认遵循 `main + topic branches + release tags`；`main` 是唯一长期主分支，stable release 只从 `main` 切
- 本节的 4 个分支是“可独立验收的集成闭环”，不是 4 个对等的 stable 发布单元；分支级验收通过不等于应立即对外发 stable
- 推荐按以下顺序分批合并，保持 `main` 持续可集成；默认只在后续完整 release preflight 与 stable smoke 通过后发一次 stable

| 顺序 | 建议分支 | 承载主题 | 对应任务 |
| --- | --- | --- | --- |
| 1 | `feature/plan-b1-resolution-core` | 先收口 resolution core：thin stub、host-aware preflight、payload index 的主解析链 | `2.1-2.7`、`3.1-3.6`、`4.1-4.2`、`4.6-4.7` |
| 2 | `feature/plan-b1-bootstrap-policy` | 再收口首次写入许可模型、ignore/commit-lock、root 选择与 bootstrap observability | `0.B.1-0.B.10`、`1.1-1.7` |
| 3 | `feature/plan-b1-diagnostics-surface` | 在前两层稳定后补 diagnostics / CLI surface / hint contract / migration visibility | `4.3-4.5`、`4.A.1-4.A.5`、`5.1-5.2`、`5.5-5.6` |
| 4 | `feature/plan-b1-regression-smoke` | 最后做回归矩阵、集成 smoke 与总验收门收口 | `5.3-5.4`、`5.A.1-5.A.3`、`6.1-6.8` |

`feature/plan-b1-resolution-core` 的内部推荐顺序补充如下：先做 `4.2 -> 4.6`，把 payload bundle 的两态解析与 legacy source 目标态收实；随后推进 `2.1 -> 2.2`，冻结 thin stub 的两态 contract 与兼容降级；再完成 `3.1 -> 3.6`，收口 ingress / preflight / resolved global bundle manifest 入口链；最后回收 `2.3 -> 2.7` 的 workspace classifier、fallback gating 与 manifest boundary。原因是 `2.3 / 2.6 / 2.7` 直接依赖 `3.4 / 3.6` 的统一解析顺序与入口暴露，若把 `2.x` 整段先于 `3.x` 全量推进，后续会被 preflight 语义反打。

### 合并与发布约束
1. 每个 topic branch 都必须先完成与自身直接相关的最小验证，再合入 `main`
2. `branch-local pass` 只表示该主题可并入主线，不表示已经满足 stable release 条件
3. `feature/plan-b1-resolution-core` 与 `feature/plan-b1-bootstrap-policy` 默认不单独发 stable；它们更适合作为后续分支的基础集成面
4. `feature/plan-b1-diagnostics-surface` 是最早可能形成 release candidate 感知的节点，但默认仍不建议单独切 stable
5. `feature/plan-b1-regression-smoke` 主要承担 closure / hardening；默认目标是补齐最终发布信心，而不是单独作为一个 stable 版本主题
6. 默认 stable 切点是 4 个分支都已合入 `main`，且通过完整 release preflight、版本一致性检查与 stable smoke 之后

## 与 Program Plan 的关系
- 本 plan 视为 `20260326_phase1-2-3-plan` 中 `Plan B1` 的升级实现窗口
- 它在 control-plane 主线优先级上高于 `Plan A / Plan D`，但执行顺序上需先经过 `20260327_hotfix` 的状态机门禁
- 它不吸收 `B2 / B3 / Plan C`
- 待 `20260327_hotfix` 与本 plan 的 control-plane contract 分别稳定后，再推进 `Plan A`

## 非目标补充
- 不在本轮提供完整的 `deactivate / clean` 命令；`B1` 只要求为未来清理埋 managed block 锚点，并暴露手动停用路径

## Post-B1 Backlog
- Migration Utility
  - 目标是把旧 vendored `.sopify-runtime/` 安全提升为 thin stub，但不进入 B1 的 DoD
- Bundle prune
  - 目标是清理未被 thin stub 引用的历史 bundle 版本，但不进入 B1 的 DoD

## 安全与性能
- 安全:
  - 不以“搬到全局”为理由绕开 manifest-first 与 no-silent-downgrade
  - 不把 `.sopify-skills` 混成控制面 locator
- 性能:
  - 只在 payload index 定位到目标版本后读取最小必要 runtime
  - 避免 per-workspace 重复复制 bundle，降低 bootstrap 成本
