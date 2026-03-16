# 任务清单

状态说明：

- `[ ]` 未开始
- `[x]` 已完成
- `[-]` 明确延后

## P0 目标

把 Sopify 做成“可控、可接入、可复用的流程壳”。

P0 实现原则：

- 优先把入口、路由、状态、上下文恢复代码化
- 优先补自用与接入闭环，不扩张外围产品层
- 只沉淀 Sopify 自己的模块边界和实现契约
- 先让现有 runtime 真正可接入，再讨论发布口径

## P0 当前最优先任务

说明：

- P0 基础骨架已经完成
- 当前最优先的是 P0 的“接入闭环”，不是新的骨架模块

### 1. 安装与接入闭环

- [x] 明确 repo-local helper 依赖的 runtime 资产范围
- [x] 消除 README 安装路径与仓库 runtime 资产之间的静默断层
- [x] 给出自用与二次接入共用的默认调用入口（`scripts/sopify_runtime.py` + `--workspace-root`）

验收条件：

- 按仓库文档接入后，不会出现“skills 装上了但 runtime 缺失”
- 自用与复用都不需要额外手工搬运隐藏文件

### 2. `~go plan` 入口接线

- [x] 为 `~go plan` 提供稳定入口
- [x] 明确入口到 `run_runtime(...)` 的调用约定
- [x] 保持现有 `~compare` 路径不被回归破坏

验收条件：

- 自用场景下可以稳定触发 `~go plan`
- 新接入者不需要理解 runtime 内部细节也能走通 plan 路径

### 3. 输出闭环

- [x] 将 `RuntimeResult` 转成 Sopify 统一输出摘要
- [x] 在 `plan_only` 路由下稳定展示方案路径、产物文件和 Next 提示
- [x] 为失败场景补充可诊断输出

验收条件：

- `~go plan` 的结果不再只是结构化对象
- 使用者看到的输出可直接用于下一步协作

### 4. 最小本地验证闭环

- [x] 固化一条 `~go plan <需求>` 的本地验证路径
- [x] 验证 plan / state / replay 产物是否稳定落盘
- [x] 验证重复调用与基础恢复路径不会破坏当前 plan 状态

验收条件：

- 自用时可以快速验证接入链路是否仍然可用
- 新接入者有一条最小可执行验证路径

### 5. 文档与边界收口

- [x] 说明当前 runtime 已经接入到哪一步
- [x] 说明当前不承诺或尚未 runtime 化的能力
- [x] 保证 README、AGENTS、蓝图任务口径一致

补充说明：

- 当前默认 repo-local runtime 入口已收口到 `scripts/sopify_runtime.py`
- `scripts/go_plan_runtime.py` 仅保留为 plan-only helper
- `~compare` 仍未在默认通用入口中自动桥接

验收条件：

- 别的开发者能快速理解“现在能用什么”
- 不会把尚未接线的能力误解为已完成资产

## P0 已完成基础项

说明：

- 以下内容属于 P0 骨架部分
- 它们已经完成，但不是当前最高优先级

### 1. runtime 骨架

- [x] 创建 `runtime/` 包与基础模块布局
- [x] 在 `runtime/models.py` 中定义共享契约
- [x] 为每个模块补一段简短的职责说明
- [x] 保持入口层足够薄，不承载流程细节

验收条件：

- runtime 包存在且结构清晰
- 模块职责边界足够明确，不会明显重叠

### 2. 零配置 config loader

- [x] 实现默认运行时配置
- [x] 实现项目级配置加载
- [x] 实现全局配置加载
- [x] 实现确定性的 merge 顺序
- [x] 只校验 P0 需要的字段
- [x] 明确不在本阶段承担宿主 CLI 配置修补

验收条件：

- 没有配置文件也能跑主流程
- 只写部分配置不会破坏运行
- 非法配置能给出明确错误

### 3. 文件系统状态契约

- [x] 建立 `.sopify-skills/state/` 路径约定
- [x] 实现 current run 读写
- [x] 实现 last route 读写
- [x] 实现 current plan 读写
- [x] 明确 active flow 的继续 / 取消 / 重置规则

验收条件：

- 当前 run 能从状态文件恢复
- 路由历史在模型上下文之外也可见

### 4. 最小上下文回收器

- [x] 定义 P0 可读取的最小上下文文件集合
- [x] 实现基于 route 的回收规则
- [x] 在 active run 场景下恢复当前 plan 摘要
- [x] 将回收结果归一化为标准上下文对象
- [x] 明确禁止全量自动加载 `.sopify-skills/`

验收条件：

- 新会话可续接当前 active run
- `~go exec` / `继续` / `下一步` 能稳定读取最小工作集
- 未命中相关路由时不会主动读取整个 KB

### 5. skill 发现

- [x] 实现基于目录约定的搜索路径
- [x] 解析内建 skills 的最小元信息
- [x] 支持可选 `skill.yaml`
- [x] 将发现结果归一化为 `SkillMeta`
- [x] 区分 advisory / workflow / runtime 三类参与方式

验收条件：

- 内建 skills 在零配置下即可发现
- 项目本地 skills 能通过约定路径被发现

### 6. 路由壳

- [x] 对命令前缀做硬路由
- [x] 对 replay / review 意图做硬路由
- [x] 对 active-state 下的 continue 意图做硬路由
- [x] 为普通输入生成 soft candidate skill set
- [x] 根据 route 上下文给出 plan level 建议
- [x] 保持 route decision 与 engine 编排解耦

验收条件：

- 命令路由具备确定性
- 普通问题仍保留模型判断空间

### 7. 方案骨架生成

- [x] 实现方案包命名规则
- [x] 实现 `light` 骨架
- [x] 实现 `standard` 骨架
- [x] 实现 `full` 骨架
- [x] 返回稳定的 artifact metadata

验收条件：

- 相同输入下骨架结构稳定
- 生成结果符合契约层模板预期

### 8. replay 写入器

- [x] 创建 run session 目录
- [x] 追加结构化事件
- [x] 生成 `session.md`
- [x] 生成 `breakdown.md`
- [x] 增加基础脱敏处理

验收条件：

- replay 产物在开启时总能落盘
- 事件历史是可读且 append-only 的

### 9. engine 编排

- [x] 在 `runtime/engine.py` 中实现标准调用顺序
- [x] 保证只有 engine 负责跨模块编排
- [x] 标准化顶层 runtime result
- [x] 将最小上下文回收纳入固定调用顺序

验收条件：

- engine 能把主路由串起来
- 不出现第二个隐藏 orchestrator

### 10. 最小 P0 测试

- [x] 测试 config merge
- [x] 测试最小上下文回收
- [x] 测试 route classification
- [x] 测试 plan scaffold 结构
- [x] 测试 replay 产物创建
- [x] 测试按目录约定发现 skill
- [x] 测试 active flow 的继续 / 取消 / 重置

验收条件：

- P0 流程壳具备行为级校验

备注：

- 当前本地已有 `tests/test_runtime.py`
- 是否纳入版本控制并接入 CI，跟随当前 P0 接入闭环一起决策

## R0 目标（后置，可选）

把 runtime skeleton 进一步收口为“可发布的最小版本”。

R0 发布范围：

- 只发布 `runtime-backed ~go plan`

R0 实现原则：

- 建立在 P0 接入闭环已经完成的前提上
- 先补发布口径、分发说明和自动化校验
- 不把 `~go exec`、history、task state、workflow-learning runtime 一起塞进首发
- 文档口径必须晚于或等于真实实现，不能继续超前承诺

## R0 任务

### 1. 发布范围收口

- [ ] 明确本次发布只承诺 `runtime-backed ~go plan`
- [ ] 明确 `~go` / `~go exec` / 回放 runtime 不属于本次发布承诺
- [ ] 同步蓝图、README、AGENTS 的能力口径

验收条件：

- 对外文档不再把未接线能力写成已可用功能
- 发布说明可以清楚描述“本次到底发布了什么”

### 2. 安装与分发闭环

- [ ] 让安装产物包含 runtime 所需代码
- [ ] 保证 Codex / Claude 两侧都能拿到一致的运行时资产
- [ ] 更新安装说明或同步脚本，消除“仓库里有代码、安装后没有”的断层

验收条件：

- 用户按 README 安装后可以获得 `~go plan` 所需运行时代码
- 安装路径与仓库结构之间不存在隐性依赖

### 3. `~go plan` 入口接线

- [ ] 为 `~go plan` 提供稳定的宿主入口
- [ ] 明确入口到 `run_runtime(...)` 的参数传递约定
- [ ] 保持现有 `~compare` 运行时路径不被这次发布回归破坏

验收条件：

- 安装后环境可以稳定触发 `~go plan`
- 不再仅靠 prompt 契约隐式完成 plan 流程

### 4. 输出适配

- [ ] 将 `RuntimeResult` 渲染为 Sopify 统一输出模板
- [ ] 在 `plan_only` 路由下稳定展示方案路径、产物文件和 Next 提示
- [ ] 为失败场景补充可诊断输出

验收条件：

- 用户看到的输出与 README 中描述的格式一致
- 成功和失败路径都具备稳定可读性

### 5. 端到端验证

- [ ] 在零配置工作区验证 `~go plan <需求>`
- [ ] 验证 plan / state / replay 产物是否稳定落盘
- [ ] 验证重复调用和跨会话恢复不会破坏当前 plan 状态

验收条件：

- 最小发布切片具备真实安装后的闭环验证
- 产物路径、命名和状态推进具备确定性

### 6. 测试与 CI

- [ ] 将 runtime 行为测试纳入版本控制
- [ ] 在 CI 中增加最小 runtime 测试 job
- [ ] 为发布切片补充至少一条安装后 smoke test 或等价验证

验收条件：

- 发布切片不再只依赖本地手工验证
- PR / push 可以自动发现这条能力的回归

### 7. 发布说明

- [ ] 更新 changelog，明确本次只发布 `runtime-backed ~go plan`
- [ ] 给出已支持、未支持、后续阶段的边界说明
- [ ] 保证 README、蓝图、变更说明三者口径一致

验收条件：

- 外部读者可以快速理解本次发布范围
- 不会把 P0 skeleton 误读为完整 runtime 发布

## P1 目标

把这个流程壳做成“会积累、会归档、会回放的长期工具”。

P1 实现原则：

- 先做最小 KB 与选择性历史回收
- 先维护索引和摘要，再考虑扩张内容面
- 优先脚本化高价值技能，不把外围产品层挤进核心
- 仅在 R0 发布稳定后进入本阶段

## P1 任务

### 1. 最小 KB 支持

- [ ] 实现 KB bootstrap
- [ ] 初始化最小 wiki 与 user 文件
- [ ] 只持久化明确的长期偏好
- [ ] 优先扫描根配置文件，再按需扫描目录结构和源码

验收条件：

- KB 可以按需初始化
- 偏好写入保持保守和结构化

### 2. 选择性历史回收

- [ ] 定义 P1 可参与回收的历史文件范围
- [ ] 优先读取 `history/index.md` 而不是直接扫描 history 全目录
- [ ] 支持按路由选择读取最近相关 replay 摘要
- [ ] 支持按需读取 `user/preferences.md` 与 `wiki/overview.md`
- [ ] 为历史回收增加数量上限和文件类型上限

验收条件：

- 历史上下文只在明确需要时加载
- 单次历史回收范围可预测且有边界
- 不会退化成全量自动加载 KB

### 3. history 归档

- [ ] 定义 archive 路径规则
- [ ] 将完成的方案包迁移到 history
- [ ] 更新 `history/index.md`
- [ ] 让后续历史回收优先依赖 index 和摘要文件

验收条件：

- 已完成方案可通过 history 查询
- 归档路径具备确定性

### 4. 任务状态跟踪

- [ ] 解析 `tasks.md` 与 `plan.md`
- [ ] 更新 `[ ] [x] [!] [-]` 标记
- [ ] 保持任务状态与 replay 事件解耦

验收条件：

- 任务推进可跨轮次保留
- 任务状态不再只隐藏在模型输出里

### 5. 高价值 skill 脚本化

- [ ] 为 `workflow-learning` 增加 runtime 脚本
- [ ] 为 `templates` 增加 runtime 脚本
- [ ] 评估 `kb` 是否需要脚本辅助

验收条件：

- 关键 skills 不再只依赖 prompt 契约

### 6. 最小 develop bridge

- [ ] 定义 `~go exec` 与 task state、replay、history 的桥接方式
- [ ] 明确不在这一阶段实现完整 develop 自动引擎

验收条件：

- `~go exec` 有显式状态推进挂点
- 实现仍然保持薄

### 7. P1 行为测试

- [ ] 测试 KB bootstrap
- [ ] 测试选择性历史回收
- [ ] 测试 history archive
- [ ] 测试 task state 更新
- [ ] 测试脚本化后的 workflow-learning

验收条件：

- P1 的积累能力具备行为级验证

## 明确延后

- [-] 深平台拆分为 `core / adapter / provider / plugin`
- [-] 重型 KB 智能同步
- [-] 全量自动加载 KB
- [-] marketplace 式扩展管理
- [-] 完整 develop 自动运行时
- [-] 大规模用户可见配置面
- [-] 安装器、升级器、通知、hooks、多 CLI 兼容层

## 阶段推进门槛

只有当下面条件成立时，才从 P0 进入 R0：

- P0 接入闭环已经完成
- 自用路径与接入路径已经跑通
- `~go plan` 已经具备稳定入口和稳定输出
- 团队确实需要再往“可发布版本”收口

只有当下面条件成立时，才从 R0 进入 P1：

- 安装后的 `~go plan` 已经稳定可用
- 文档承诺与真实能力已经一致
- runtime 测试已经进仓并接入 CI
- 最小发布切片已经完成至少一轮真实验证
