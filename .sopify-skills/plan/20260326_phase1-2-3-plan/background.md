# 变更提案: Sopify 推广优化总纲与后续拆分路线

## 需求背景
当前讨论的优化方向集中在三类真实推广痛点上：

1. 侵入性与冷启动成本偏高
2. checkpoint / handoff 过于频繁，影响连续编码心流
3. 进入 active plan 后，旁路修补与恢复主线的成本偏高

这些问题成立，但不能作为一个大重构一次性处理。当前实现里至少有三条独立合约线：

1. 风险打断线
   涉及 `runtime/execution_gate.py`、`runtime/execution_confirm.py`、`runtime/decision_policy.py`
2. 物化与路径线
   涉及 `installer/bootstrap_workspace.py`、`installer/runtime_bundle.py`、`runtime/config.py`
3. 状态机与恢复线
   涉及 `runtime/state.py`、`runtime/handoff.py`、`runtime/develop_checkpoint.py`

如果把 Ghost、Trust Levels、Suspend/Resume 一起改，会同时打散 `ExecutionGate`、workspace path、handoff/state 三套机器契约，回滚与验证都不可控。

因此本方案的定位不是直接开工，而是作为 program-level 总 plan，统一收口结论、明确后续拆分顺序、锁定哪些事项必须先拍板。

## 变更内容
本总 plan 收口以下结论：

1. 必须拆分为多个后续子 plan，而不是保留一个大执行单
2. `Ghost Mode` 必须分解为不同里程碑，不能用一个词覆盖不同量级的改动
3. `ExecutionGate` 的核心机器语义需要在风险打断 plan 中保持稳定
4. 对外文档只能宣传已交付能力，不能预售未来路线

本总 plan 不直接落代码，只负责：

1. 明确后续子 plan 的边界与依赖
2. 明确 committed now / deferred / direction decisions required
3. 为后续子 plan 建立 acceptance gate

## 影响范围
- 模块:
  - `runtime/execution_gate.py`
  - `runtime/execution_confirm.py`
  - `runtime/decision_policy.py`
  - `runtime/config.py`
  - `runtime/state.py`
  - `runtime/handoff.py`
  - `runtime/develop_checkpoint.py`
  - `runtime/knowledge_layout.py`
  - `runtime/finalize.py`
  - `runtime/router.py`
  - `README.md`
  - `README.zh-CN.md`
  - `docs/how-sopify-works.en.md`
- 文件边界:
  - 本轮只改总纲 plan 文件
  - 不直接修改 runtime / installer 实现
  - 后续子 plan 才各自收口到代码范围

## 风险评估
- 风险: 把 `Ghost State` 和 `Ghost Knowledge` 混成一个 plan，导致 `plan_path`、`knowledge_layout`、`finalize`、`router` 一起改动，范围失控
- 缓解: 将 Ghost 方案拆成 `B1 延迟物化`、`B2 Ghost State`、`B3 Ghost Knowledge` 三层，并明确 `B3` 延后独立立项
- 风险: 在风险自适应打断中误改 `ExecutionGate` 核心语义，破坏 decision / handoff / output 消费链
- 缓解: 冻结 `gate_status` 值集与核心字段名，仅允许在受控前提下扩展 `blocking_reason`
- 风险: 在对外文档中提前承诺未交付的 Ghost / side-task 能力，造成产品承诺超前
- 缓解: 文档子 plan 仅在已交付能力基础上更新对外叙事
