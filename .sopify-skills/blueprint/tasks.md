# 蓝图任务

状态: 只保留未完成长期项与明确延后项；已完成项不继续留在本文件。

## 未完成长期项

- [ ] 补宿主级 first-hop ingress proof / doctor，让 host-first runtime gate 有独立可见性与诊断闭环。
- [ ] 把 `~compare` 的 shortlist facade 收敛进默认主链路恢复，复用统一的 decision checkpoint machine contract。
- [ ] 补 `workflow-learning` 的独立 runtime helper 与更稳定的按任务/按日期 replay retrieval。
- [ ] 评估是否引入 blueprint 索引摘要的更细粒度自动刷新。
- [ ] 评估是否为 history 建立更紧凑的 feature_key 聚合视图。

## 明确延后项

- [-] runtime 全接管 develop orchestrator；当前阶段保持 host-owned develop + standardized checkpoint callback。
- [-] 非 CLI 宿主的图形化 clarification / decision 表单；当前正式范围仍是 CLI bridge。
- [-] 把 history 正文纳入默认长期上下文；当前只保留索引发现，不作为默认消费源。
- [-] `daily index` 降级为后续可选能力，仅在需要提速或更稳定按天检索时再评估引入。
- [-] `~replay` 与更多按日期 retrieval 入口保留后续能力，不进入当前主线。
- [-] 摘要质量优化与验证结果摄取降为后续长期优化，不阻塞本期主线收口。
- [-] 基于 replay activation 的时间线增强保留后续能力，不进入首版交付面。
- [-] runtime 独立 `preferences_artifact` 保留后续评估，不进入首版范围。
- [-] 偏好分类、自动归纳、自动提炼保留后续评估，不进入首版范围。
- [-] 基于 Batch 2/3 证据回写 `A1` business clarifier 与 `A4` abstraction caution 的 wording/examples；当前不阻塞已通过的 promotion decision。
