# 技术设计: B1 升级为全局 Bundle + 本地 Thin Stub/Pin + Ignore/兼容迁移

## 技术方案
- 核心目标: 将原 `Plan B1` 从“延迟物化”升级为完整的 control-plane decoupling 方案，收口 global bundle、thin stub、bootstrap ignore、host-aware preflight 与 legacy compatibility
- 设计结论:
  - workspace 继续保留 `.sopify-runtime/manifest.json` 作为本地控制面入口，但不再复制重型 runtime 代码
  - 重型 Python runtime 与相关 manifest-first control-plane 逻辑保留在宿主全局 payload 中，以 versioned bundle store 管理
  - `.sopify-skills/` 继续只承载知识与状态，不承担全局 bundle locator 的 first-hop 入口职责

## 前置产品决策 | 首次写入许可模型
- 本条款是 `Plan B1` 的前置产品决策，优先级高于 `bootstrap / thin stub / host-aware preflight / payload index` 的具体实现拆分
- 本条款只冻结一件事：`首次何时允许向 workspace 写入 Sopify 控制面资产`

### 决策结论
1. 默认禁止纯语义自动 bootstrap
   - 自然语言复杂度识别、任务规模判断、语义路由结果，均不得直接触发首次写入 workspace

2. 首次写入只允许发生在两类入口
   - 显式强意图命令：`~go` / `~go plan` / `~go init`
   - 宿主先展示 `confirm_bootstrap` 类 checkpoint，且用户明确确认

3. 语义判定层只负责提议，不负责授权
   - 语义层只能输出结构化 intent proposal
   - 不得直接驱动 `bootstrap / plan scaffold / proposal materialization / workspace write`

4. 首次 auto-bootstrap 默认只写 thin stub
   - 默认只落 `.sopify-runtime/manifest.json` 等最小控制面资产
   - 不默认生成 `sopify.config.yaml`

5. 已激活 workspace 不等于强制进入 planning
   - “已激活”只表示该项目允许 Sopify control-plane 介入
   - 后续请求仍按 `consult / minimal / adaptive` 正常路由，不得把激活态等同于“所有请求都强管控”

### 硬约束
1. `~compare`、`~go finalize` 默认不视为首次 bootstrap 的强意图入口
2. agent / 局部语境识别只可用于三分流：`no_write_consult`、`ask_confirm`、`explicit_allow`
3. 首次写入授权必须发生在 host ingress / preflight 侧，不允许把“先 bootstrap 再确认”下沉到 repo-local runtime
4. 必须保留窄口 brake layer，对 `不要改 / 先分析 / 只解释 / 不写文件 / explain-only` 这类高确定性表达优先阻断写入意图
5. `non-interactive / readonly / non-git / monorepo` 场景必须有确定性降级，不得卡在确认、不得 silent activation、不得静默写到错误 root
6. 所有授权路径都必须产出稳定 reason code，禁止 silent bootstrap，禁止 silent downgrade

### 非目标
- 不在本轮引入“纯全局 auto-bootstrap 开关”作为主模型
- 不在本轮把 agent 判定扩展为自由式路由裁决器
- 不在本轮把 `B2 / B3 / Plan C / Plan A` 语义并入本决策

### 与实施顺序的关系
1. 先冻结本条款，再进入 `P0-P4` 的实现拆分
2. `thin stub / ignore / host-aware preflight / payload index` 均需服从本条款
3. `B2` 只继承该授权模型，不得在后续全局 state 改造中重新打开“纯语义自动激活”路径

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
- `written_by_host`

约束：
- thin stub 只表达“当前项目要找哪一版、允许哪些最低能力、是否允许 legacy fallback”
- thin stub 不是 `.sopify-skills` 的一部分
- “提交版本锁”是可选模式，不作为默认要求

### 3. 解析顺序
新 preflight 顺序应固定为：

1. 读取 workspace-local thin stub
2. 由当前 host adapter 解析 payload root
3. 从 payload index 定位目标 global bundle
4. 读取 global bundle manifest
5. 由该 manifest 暴露的 `runtime_gate_entry / preferences_preload_entry` 执行控制面主链
6. 仅当 thin stub 缺失或声明允许时，才进入 legacy vendored fallback

### 4. Ignore 默认值
默认策略：

1. git 仓库优先写 `.git/info/exclude`
2. 仅在“提交版本锁”模式才更新 `.gitignore`
3. 非 git 仓库给出可见但不阻断的降级提示

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

5. 兼容迁移必须有可观测 reason code
   - `stub 优先`
   - `legacy vendored fallback 次之`
   - `no_silent_downgrade`

## 实施前确认清单
以下 4 项需在开工前确认，否则实现阶段容易再次分叉：

1. thin stub 字段值域与默认值
   - 特别是 `locator_mode`、`legacy_fallback`、`required_capabilities` 的允许值、默认值与缺失时行为

2. reason code 的产出/消费与 fail-closed 边界
   - 需要明确哪些模块负责产出，哪些消费，以及哪些情况阻断、哪些情况仅可见提示

3. dual-host host hint 来源与冲突优先级
   - 需要明确 host hint 从哪来，以及显式 host hint 与自动探测冲突时谁优先

4. commit-lock mode 的启用入口
   - 需要明确它是 CLI 参数、配置项还是 bootstrap 选项

## 实施边界

### P0 | Bootstrap 与 Ignore 基线
- bootstrap 增加 ignore writer
- 默认写 `.git/info/exclude`
- 定义 commit-lock mode 下的 `.gitignore` 行为
- 定义 non-git repository 的降级输出

### P1 | Thin Stub Contract
- 定义 thin stub schema
- 改写 workspace classifier，不再要求 `_REQUIRED_BUNDLE_FILES`
- 分离 workspace stub 校验与 global bundle 校验

### P2 | Host-Aware Preflight
- 让 preflight 显式接收 host payload 解析上下文
- 删除把 `.codex` / `.claude` 固定探测顺序当成最终判定依据的逻辑
- 建立 `stub -> global bundle -> manifest-first gate/preload -> legacy fallback` 的统一顺序

### P3 | Payload Index 与 Diagnostics
- payload 从单 `bundle/` 迁移到 versioned bundle store
- `validate / inspection / doctor / status / smoke / distribution` 同步升级
- 迁移窗口兼容旧 `bundle/` 结构，但输出明确 reason code

### P4 | Compatibility / Tests / Migration
- 为 stub-first 与 legacy fallback 补 reason code 矩阵
- 为 dual-host / old workspace / non-git 仓库补回归测试
- 同步总纲与迁移说明

## 验收门
1. 新 workspace bootstrap 后只落 thin stub，不再复制整包 runtime
2. dual-host 同仓库场景下，payload 选择由 host-aware contract 决定，不再靠目录探测顺序兜底
3. payload index 升级后，`validate / inspection / doctor / status / smoke` 全部通过
4. git 仓库默认不制造 repo-level 脏 diff；commit-lock mode 行为可控
5. legacy vendored workspace 仍可运行，但 fallback 状态在 bootstrap / doctor / status 中可见
6. `plan/blueprint/history` 与 `plan_path / finalize / knowledge_layout` 的语义保持不变

## 与 Program Plan 的关系
- 本 plan 视为 `20260326_phase1-2-3-plan` 中 `Plan B1` 的升级实现窗口
- 它优先级高于 `Plan A / Plan D`，因为当前首要痛点是 adoption friction 与 control-plane 侵入感
- 它不吸收 `B2 / B3 / Plan C`
- 待本 plan 的 control-plane contract 稳定后，再推进 `Plan A`

## 安全与性能
- 安全:
  - 不以“搬到全局”为理由绕开 manifest-first 与 no-silent-downgrade
  - 不把 `.sopify-skills` 混成控制面 locator
- 性能:
  - 只在 payload index 定位到目标版本后读取最小必要 runtime
  - 避免 per-workspace 重复复制 bundle，降低 bootstrap 成本
