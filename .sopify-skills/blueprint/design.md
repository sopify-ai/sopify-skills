# 文档治理蓝图设计

状态: 文档已收口，待实现
创建日期: 2026-03-17

## 设计原则

1. 默认行为优先于用户配置
2. 工程化生命周期优先于语义化记忆
3. 索引与深层文档分层，避免首次触发写得过重
4. 单活动 plan 优先，历史归档延后到收口时
5. Blueprint 是长期真相；plan/history 是执行资产

## 目录契约

```text
.sopify-skills/
├── blueprint/              # 项目级长期蓝图，默认进入版本管理
│   ├── README.md           # 项目入口索引，首次触发即可创建
│   ├── background.md       # 长期目标、边界、约束、非目标
│   ├── design.md           # 模块边界、宿主契约、目录契约、关键数据流
│   └── tasks.md            # 长期演进项与待办
├── plan/                   # 当前活动方案，默认忽略
│   └── YYYYMMDD_feature/
├── history/                # 收口归档，默认忽略
│   ├── index.md
│   └── YYYY-MM/
│       └── YYYYMMDD_feature/
├── state/                  # 运行态状态，始终忽略
└── replay/                 # 可选回放能力，始终忽略
```

## 首次触发生命周期

### A. 首次 Sopify 触发

在 runtime 固定入口中执行 `ensure_blueprint_index(...)`：

- 不依赖用户命令是否进入 plan
- 不依赖咨询/设计/开发语义
- 只依赖“当前目录是否为真实项目仓库”的机器判定

真实项目仓库判定建议：

- 命中以下任一条件即视为真实项目：
  - 存在 `.git/`
  - 存在 `package.json / pyproject.toml / go.mod / Cargo.toml / pom.xml / build.gradle`
  - 存在 `src / app / lib / tests / scripts` 等目录

若命中且 `blueprint/README.md` 缺失：

- 只创建 `blueprint/README.md`
- 不在咨询场景强行创建 `background.md / design.md / tasks.md`

### B. 首次进入 plan 生命周期

进入 `plan_only / workflow / light_iterate` 时：

- 若 `blueprint/background.md / design.md / tasks.md` 缺失，则补齐
- 创建当前活动 `plan/`
- 写入本次方案的机器元数据

## Blueprint README 强约束模板

`blueprint/README.md` 是项目级全局索引，必须固定包含以下区块：

1. 当前目标
2. 项目概览
3. 架构地图
4. 关键契约
5. 当前焦点
6. 深入阅读入口

其中索引性区块采用托管标记，便于后续自动刷新：

```md
<!-- sopify:auto:goal:start -->
...
<!-- sopify:auto:goal:end -->
```

设计要求：

- 托管区块只写高密度摘要，不写长篇论证
- 非托管区块允许人工补充背景说明
- 自动刷新只更新托管区块，不覆盖人工说明

## Plan 元数据契约

不新增独立元数据文件，优先使用现有 plan 文件头部承载机器字段：

- `light`: 写入 `plan.md`
- `standard / full`: 写入 `tasks.md`

最小字段建议：

```yaml
plan_id:
feature_key:
level: light|standard|full
lifecycle_state: active|ready_for_verify|archived
blueprint_obligation: index_only|review_required|design_required
archive_ready: false
```

默认映射：

- `light` -> `index_only`
- `standard` -> `review_required`
- `full` -> `design_required`

说明：

- `standard` 是否真的需要更新深层 blueprint，不再完全依赖语义猜测，而是在收口阶段结合改动类型与 obligation 共同判断
- `full` 视为必须同步深层 blueprint

## 收口事务

不依赖 commit hook；使用固定的“收口事务”统一完成文档生命周期。

建议事务顺序：

1. 校验当前 plan 是否达到 `ready_for_verify`
2. 刷新 `blueprint/README.md` 托管区块
3. 根据 `blueprint_obligation` 判断是否要求更新 `background.md / design.md / tasks.md`
4. 归档当前 plan 到 `history/YYYY-MM/...`
5. 更新 `history/index.md`
6. 清理或更新 `current_plan / current_run / current_handoff`

## Blueprint 更新规则

### Light

- 不要求更新深层 blueprint
- 允许只刷新 `blueprint/README.md` 的索引摘要

### Standard

仅在以下任一条件命中时，要求更新深层 blueprint：

- 模块边界变化
- 宿主接入契约变化
- manifest / handoff 契约变化
- 目录契约变化
- 长期技术约定变化

### Full

- 必须更新 `background.md / design.md / tasks.md`
- `README.md` 同步刷新当前焦点、关键契约与阅读入口

## History 契约

`history/` 只在“本轮任务收口、准备交付验证”时写入：

- 平时不与当前 `plan/` 双写
- 不做实时镜像
- 不做多个 plan 自动归并

单次 plan 的归档规则：

- 一个活动 plan 对应一个归档目录
- `history/index.md` 只记录摘要索引
- 归档后 `plan/` 中不再保留该活动方案的工作态职责

## Replay 契约

- `replay/` 保持为可选能力
- 不作为“接入 Sopify 后必须完整支持”的基础文档治理要求
- 若启用 `workflow-learning`，仍可按独立能力写入本地 replay 资产

## 与决策确认能力的衔接

决策确认能力（decision checkpoint）应建立在本蓝图之上：

1. 仅在 design 阶段自动触发
2. 触发时先暂停正式 plan 生成
3. 将待确认状态写入 `state/current_decision.json`
4. 用户确认后再生成唯一正式 plan
5. 选择结果先写入当前 plan
6. 若形成长期稳定结论，再在收口时同步到 blueprint

这样可以同时满足：

- 不引入多份 draft plan
- 不要求用户额外配置
- 不把关键决策只留在聊天上下文里

## 读取优先级建议

给宿主与 LLM 的默认读取顺序：

1. `project.md`
2. `blueprint/README.md`
3. `wiki/overview.md`
4. 当前活动 `plan/`
5. 按需进入 `blueprint/design.md / background.md`
6. 只有在需要追溯旧方案时才查看 `history/`

这样可以形成稳定的渐进式披露：

- 先读索引
- 再读当前任务
- 最后按需追溯历史
