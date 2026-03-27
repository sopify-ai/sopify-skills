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
- [x] 1.2 明确后续方案拆为 `A / D / B1 / B2 / C / B3`
- [x] 1.3 明确本总 plan 仅负责方向收口、依赖管理、待拍板项管理

## 2. 待拍板决策
- [ ] 2.1 锁定默认策略档位是否为 `balanced`
- [ ] 2.2 锁定 Ghost 是否为 `opt-in`
- [ ] 2.3 锁定 Ghost v1 是否止步于 `B2`
- [ ] 2.4 锁定 side task 是否强约束为 `low-risk only`

## 3. 后续子 plan 入口
- [ ] 3.1 先完成 `20260326_5-plan-20260326-phase1-2-3-plan-plan-20260326-ph`，作为升级版 Plan B1（global bundle + thin stub/pin + ignore + compatibility）
- [ ] 3.2 在 3.1 的 control-plane contract 稳定后推进 Plan A 子 plan
- [ ] 3.3 在 Plan A 与 3.1 的对外语义都稳定后推进 Plan D 子 plan
- [ ] 3.4 在 control-plane decoupling 稳定后，再评估是否需要推进 Plan B2
- [ ] 3.5 在 Plan A 风险边界与 control-plane contract 稳定后推进 Plan C 子 plan
- [ ] 3.6 将 Plan B3 保持为显式延后项，不并入 3.1 / B2

## 4. 子 plan 统一门禁
- [ ] 4.1 为每个后续子 plan 显式写出 non-goals，避免范围滑移
- [ ] 4.2 为每个后续子 plan 显式写出 acceptance gate
- [ ] 4.3 在 Plan A 中冻结 `ExecutionGate` 核心字段名与 `gate_status` 值集
- [ ] 4.4 在 Plan B2 中明确“不改变 plan/blueprint/history contract”
- [ ] 4.5 在 Plan C 中明确“bounded side task，不允许自由漫游”
- [ ] 4.6 在升级版 Plan B1 中将 thin stub 校验、dual-host host-aware、payload index、ignore 默认值、legacy fallback reason code 作为硬门禁

## 5. 明确延后方向
- [ ] 5.1 若未来启动 B3，单独拍板 `plan_path` 新语义
- [ ] 5.2 若未来启动 B3，单独拍板 Ghost 下 `finalize/history` 行为
- [ ] 5.3 若未来启动 B3，单独拍板 mixed-mode 协作边界
