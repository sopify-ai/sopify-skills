# Sopify Runtime 蓝图

状态: 进行中（P0 runtime skeleton 已落地，R0 最小可发布版本待收口）
创建日期: 2026-03-13
维护方式: 持续更新

## 这份文档是做什么的

这是一套持续维护的实施蓝图，用来指导 Sopify 从“以 prompt 规则为主的技能包”演进为“可控的流程壳”。

路线分三阶段：

- P0: 先把 Sopify 做成可控的流程壳
- R0: 再把其中最小可发布切片收口成可安装、可触发、可验证的版本
- P1: 再把这个流程壳做成会积累、会归档、会回放的长期工具

## 当前方向

- 第一原则: 默认无配置也能跑主流程
- 命令和状态流转由 Sopify 硬控
- 具体 skill 选择仍保留模型判断空间
- 扩展优先靠目录约定和轻 manifest
- 入口、路由、状态、上下文恢复优先代码化，不依赖长 prompt 兜底
- 先收口最小可发布切片，再扩张长期能力
- 高价值规则优先脚本化，先收口核心流程，再考虑外围产品层
- 上下文恢复依赖 runtime 主动回收本地状态，不依赖模型记忆
- 禁止全量自动加载 `.sopify-skills/` 知识库
- 在 runtime 稳定前，不做深平台架构

## 为什么放在这里

这套蓝图放在 `.sopify-skills/plan/`，而不是 `articles/`。

- `articles/` 更适合对外文章、草稿和宣传材料
- `.sopify-skills/plan/` 更适合长期维护的内部实施方案
- 路径也符合 Sopify 自己的方案包约定

## 文档结构

- `background.md`: 背景、目标、约束、缺口、成功标准
- `design.md`: 架构蓝图、模块边界、状态模型、扩展约定
- `tasks.md`: P0 / R0 / P1 执行清单与验收条件

## 更新顺序

当方向变化时，按下面顺序更新：

1. 目标或约束变化，先改 `background.md`
2. 模块边界或架构决策变化，再改 `design.md`
3. 范围、顺序、验收条件变化，最后改 `tasks.md`
4. 只有阶段摘要变化时，才改本文件

## 阶段摘要

### P0

交付一个薄 runtime，至少能稳定完成：

- 以稳定入口承接主流程
- 以安全默认值加载配置
- 稳定分类路由
- 按约定发现 skills
- 将运行状态持久化到文件系统
- 回收最小必要上下文以支持跨会话续跑
- 生成固定结构的方案包
- 记录 replay 产物

当前已落地：

- `runtime/` 包与共享契约
- `config / state / context_recovery / skill_registry / router`
- `plan_scaffold / replay / skill_runner / engine`
- 本地 `tests/test_runtime.py` 行为测试

说明：

- P0 代表本地工程骨架已经形成
- P0 不等于已经形成可对外发布的完整功能

### R0

交付一个最小可发布版本，只承诺一条发布切片：

- `runtime-backed ~go plan`

R0 需要补齐：

- 安装产物必须包含 runtime 所需代码
- 安装后要有稳定入口把 `~go plan` 接到 runtime
- `RuntimeResult` 需要有面向用户的输出渲染层
- 零配置下要稳定生成 plan / state / replay 产物
- 文档、测试和 CI 必须与真实能力一致

当前已收口：

- 仓库内新增 `scripts/sopify_runtime.py` 作为默认 repo-local 原始输入入口
- `scripts/go_plan_runtime.py` 退回为 plan-only helper
- `runtime/output.py` 已将 `RuntimeResult` 渲染为 Sopify 统一摘要
- 本地验证已覆盖 plan / state / replay 落盘与重复执行目录冲突处理
- README、AGENTS、design skill、蓝图任务单口径已对齐

当前仍未收口：

- 面向安装分发的 runtime 资产自动同步
- CI 与进仓测试纳入
- `~compare` 的通用入口自动桥接
- `~go exec` / `workflow-learning` 的独立 runtime helper

### P1

在 R0 的基础上，继续补齐长期能力：

- 初始化最小知识库
- 按路由选择性回收历史上下文
- 归档完成的方案到 history
- 跟踪任务状态推进
- 将高价值 skills 脚本化，例如 `workflow-learning` 和 `templates`
- 继续保持核心流程与外围产品层解耦

## 当前明确不做

- 不做深 `core / adapter / provider / plugin` 拆分
- 不扩张面向用户的配置面
- 不做全量自动加载 KB
- R0 不发布 `~go exec` 的最小 develop bridge
- R0 不发布 `workflow-learning` / `templates` 的 runtime 脚本化
- R0 不发布 history / task state / KB bootstrap
- P0 不做完整 develop 自动执行器
- P0 / P1 不优先做安装器、更新器、通知、hooks 等外围产品层
- 不做 marketplace 式 skill 平台
