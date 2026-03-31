---
plan_id: 20260326_phase1-2-3-plan
feature_key: phase1-2-3-plan
level: standard
lifecycle_state: active
knowledge_sync:
  project: review
  background: review
  design: review
  tasks: review
archive_ready: false
---

# 任务清单: Sopify 推广优化总纲与后续拆分路线

## 1. 总纲结论
- [x] 1.1 明确当前优化不应作为一个大执行 plan 直接开工
- [x] 1.2 明确后续方案拆为 `H / A / D / B1 / B2 / C / B3`
- [x] 1.3 明确本总 plan 仅负责方向收口、依赖管理、待拍板项管理
- [x] 1.4 明确 `20260327_hotfix` 作为 `B1` 的前置门禁；`B1` 在其完成前仅保留可并行的纯 control-plane 结构工作

## 2. 待拍板决策
- [ ] 2.1 锁定默认策略档位是否为 `balanced`
- [ ] 2.2 锁定 Ghost 是否为 `opt-in`
- [ ] 2.3 锁定 Ghost v1 是否止步于 `B2`
- [ ] 2.4 锁定 side task 是否强约束为 `low-risk only`

## 3. 后续子 plan 入口
- [x] 3.1 先完成 `20260327_hotfix`，作为状态机一致性前置门禁
- [ ] 3.2 在 3.1 解除状态链路阻塞后继续 `20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph`，作为升级版 Plan B1（global bundle + thin stub/pin + ignore + compatibility）
- [ ] 3.3 在 3.2 的 control-plane contract 稳定后推进 Plan A 子 plan
- [ ] 3.4 在 Plan A 与 3.2 的对外语义都稳定后推进 Plan D 子 plan
- [ ] 3.5 在 control-plane decoupling 稳定后，再评估是否需要推进 Plan B2
- [ ] 3.6 在 Plan A 风险边界与 control-plane contract 稳定后推进 Plan C 子 plan
- [ ] 3.7 将 Plan B3 保持为显式延后项，不并入 3.2 / B2

## 4. 子 plan 统一门禁
- [ ] 4.1 为每个后续子 plan 显式写出 non-goals，避免范围滑移
- [ ] 4.2 为每个后续子 plan 显式写出 acceptance gate
- [x] 4.3 在 `20260327_hotfix` 中冻结 `snapshot-only resolver / proposal session-only / state_conflict + abort / unique handoff exit`
- [ ] 4.4 在升级版 Plan B1 中将 thin stub 校验、dual-host host-aware、payload index、ignore 默认值、legacy fallback reason code 作为硬门禁
- [ ] 4.5 在 Plan A 子 plan 启动前登记 carry-over recall debt 与明确 non-goals，避免把 Plan H correctness hotfix 与后续语义召回增强混做一轮
- [ ] 4.6 为 Plan A 子 plan 明确启动触发条件（真实漏判样本 / 用户反馈阈值），避免长期后延或提前侵入 B1 窗口
- [ ] 4.7 在 Plan A 中冻结 `ExecutionGate` 核心字段名与 `gate_status` 值集
- [ ] 4.8 在 Plan B2 中明确“不改变 plan/blueprint/history contract”
- [ ] 4.9 在 Plan C 中明确“bounded side task，不允许自由漫游”
- [ ] 4.10 在 Plan A 子 plan 中覆盖 `ready_for_execution + state_conflict(abort_conflict)` 收敛 case：必须验证“开始执行 -> state_conflict -> 取消 -> 再次开始执行”不再回环冲突，并沉淀可追溯证据链（`current_gate_receipt / current_run / current_handoff / last_route`）与对应代码链路（`context_snapshot -> router -> engine -> handoff`）
- [x] 4.11 冻结后续设计边界：`B1` 收口后可先灰度推广；`Plan A / Plan D` 默认必须向后兼容已发布 `B1` contract，不得隐式引入破坏性变更；若需破坏性改动，必须单独立项并附迁移/回滚方案
- [x] 4.12 在 Plan A 进入实现前冻结 A0 语义契约：按“同一语义类一次收口”设计，不接受“单词/短语补丁式”修复
- [x] 4.13 在 Plan A 子 plan 中为 `question signal + retopic signal + plan referent` 建立结构化语义类矩阵（后缀/前置/中置疑问）
- [x] 4.14 将 Case A-7 的验收矩阵固化为 parser 正反例与回归用例；通过标准必须包含“inspect fail-close + revise 保持 + mixed case 保持”
- [ ] 4.15 将 `plan_proposal_pending + command prefix` 标记为“行为约束待产品确认”并与 parser 收口任务解耦，避免在同一轮混改

## 5. 明确延后方向
- [ ] 5.1 若未来启动 B3，单独拍板 `plan_path` 新语义
- [ ] 5.2 若未来启动 B3，单独拍板 Ghost 下 `finalize/history` 行为
- [ ] 5.3 若未来启动 B3，单独拍板 mixed-mode 协作边界
