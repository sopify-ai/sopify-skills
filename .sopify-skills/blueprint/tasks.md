# 任务清单: 文档治理与索引架构

状态: 文档已收口，进入实现排期

状态说明：

- `[ ]` 未开始
- `[x]` 已完成
- `[-]` 明确延后

说明：

- 本清单中的 `[x]` 表示文档、模板或仓库默认策略已收口，不等于 runtime 自动化已经落地

## 0. 蓝图文档

- [x] 0.1 建立 `.sopify-skills/blueprint/` 正式目录
- [x] 0.2 写入 `README.md / background.md / design.md / tasks.md`
- [x] 0.3 明确零配置开箱即用、首次触发索引 bootstrap、plan 收口归档、decision checkpoint 前后关系
- [x] 0.4 吸收旧 `20260313_sopify_runtime_blueprint` 的有效内容，并迁移到新的 `blueprint/` 口径

验收标准：

- 仓库内已有一套正式、可实施的文档治理蓝图
- 后续实现不需要再从聊天记录里反推规则
- 旧 runtime 蓝图不再需要继续双维护

## 1. Blueprint Index Bootstrap

- [ ] 1.1 在 runtime 固定入口增加 `ensure_blueprint_index(...)`
- [ ] 1.2 固化“真实项目仓库”判定规则
- [ ] 1.3 首次 Sopify 触发时，仅在缺失时创建 `blueprint/README.md`
- [ ] 1.4 保持咨询场景也可创建索引文件，但不创建完整深层 blueprint
- [ ] 1.5 为首次触发创建索引的行为补测试

验收标准：

- 不要求用户额外配置
- 首次触发 Sopify 即可为真实项目建立全局入口索引

## 2. Blueprint 强约束模板

- [x] 2.1 固化 `blueprint/README.md` 的 6 个固定区块
- [x] 2.2 设计托管区块标记 `<!-- sopify:auto:* -->`
- [x] 2.3 限定自动刷新只覆盖托管区块
- [x] 2.4 保留非托管区块用于人工补充
- [ ] 2.5 为 README 模板与托管区块补测试

验收标准：

- 人和 LLM 都能稳定把 `blueprint/README.md` 当项目入口索引
- 自动刷新不会覆盖人工维护说明

## 3. 首次进入 Plan 生命周期时补齐完整 Blueprint

- [ ] 3.1 在 `plan_only / workflow / light_iterate` 路由下补齐 `background.md / design.md / tasks.md`
- [ ] 3.2 保持 blueprint 深层文件只在首次 plan 生命周期创建
- [ ] 3.3 确保首次 plan 生命周期与首次索引 bootstrap 不冲突
- [ ] 3.4 为首次 plan 生命周期补齐完整 blueprint 的行为补测试

验收标准：

- 咨询场景不写重文档
- 一旦真正进入方案流，项目就拥有完整 blueprint 骨架

## 4. Plan 元数据契约

- [ ] 4.1 在 `plan.md` 或 `tasks.md` 头部增加机器字段
- [ ] 4.2 固化 `lifecycle_state` 状态集合
- [ ] 4.3 固化 `blueprint_obligation` 状态集合
- [ ] 4.4 建立 `light / standard / full` 到 obligation 的默认映射
- [ ] 4.5 为元数据读写与兼容补测试

验收标准：

- blueprint 是否必须更新不再只靠语义判断
- 收口逻辑可直接读取 plan 元数据

## 5. 收口事务

- [ ] 5.1 引入统一 `finalize_plan(...)` 收口事务
- [ ] 5.2 在收口事务中刷新 `blueprint/README.md` 的索引区块
- [ ] 5.3 在收口事务中检查 `blueprint_obligation`
- [ ] 5.4 在收口事务中完成 `plan -> history` 归档
- [ ] 5.5 在收口事务中更新 `history/index.md`
- [ ] 5.6 在收口事务中清理活动状态

验收标准：

- 不依赖 commit hook
- 文档更新、归档、状态收口通过固定事务完成

## 6. Blueprint 更新规则

- [ ] 6.1 固化 `light` 只刷新索引、不强制改深层 blueprint
- [ ] 6.2 固化 `standard` 在边界或契约变化时更新深层 blueprint
- [ ] 6.3 固化 `full` 必须更新深层 blueprint
- [ ] 6.4 为 `standard` 的命中条件建立可测试判定规则
- [ ] 6.5 为 `full` 缺失深层更新的场景补失败提示

验收标准：

- `light / standard / full` 的文档责任边界清晰稳定
- 不会让简单任务被重文档拖慢，也不会让架构级变更无痕通过

## 7. History 策略

- [x] 7.1 明确 `history/` 只在收口时写入
- [x] 7.2 明确 `history/` 不做实时镜像
- [x] 7.3 明确 `history/` 不做多个 plan 自动归并
- [x] 7.4 在 `history/index.md` 中保留摘要索引格式
- [ ] 7.5 为归档与索引更新补测试

验收标准：

- 当前 plan 与归档 history 的职责明确
- 历史信息可追溯但不会干扰当前工作区

## 8. 默认 Git 策略

- [x] 8.1 将 `blueprint/` 设为默认入库目录
- [x] 8.2 将 `plan/` 设为默认忽略目录
- [x] 8.3 将 `history/` 设为默认忽略目录
- [x] 8.4 将 `state/` 与 `replay/` 继续设为默认忽略目录
- [x] 8.5 在文档中保留“用户可自行调整 `.gitignore`”的说明

验收标准：

- 默认策略开箱即用
- 用户如有特殊需要，仍可自行调整入库范围

## 9. 决策确认能力前置准备

- [ ] 9.1 让 design 阶段支持“先决策确认，再生成正式 plan”的生命周期
- [ ] 9.2 定义 `current_decision.json` 与当前 plan 的衔接方式
- [ ] 9.3 明确用户选择结果先写 plan，再在收口时按需写 blueprint
- [ ] 9.4 保持不生成多份 draft plan
- [ ] 9.5 在正式实现 decision checkpoint 前，先完成这里的文档与状态契约准备

验收标准：

- 后续实现决策确认能力时，不需要再推翻当前文档治理模型
- “用户拍板后继续生成唯一正式 plan”成为固定主路径

## 10. 文档与测试收口

- [x] 10.1 更新 README，解释 blueprint / plan / history / replay 的边界
- [x] 10.2 更新 AGENTS/CLAUDE 文档，解释 blueprint 的默认行为
- [ ] 10.3 更新 templates skill，补 blueprint 模板
- [ ] 10.4 更新 kb/develop/design skill，接入 blueprint 生命周期
- [ ] 10.5 增加 blueprint bootstrap、托管区块、收口事务、history 归档的自动化测试

验收标准：

- README、宿主文档、skill 文档、runtime 行为口径一致
- 下游项目接入 Sopify 后可以完整复用这套文档治理模型

## 11. 第二阶段

- [ ] 11.1 实现 design 决策确认能力（decision checkpoint）
- [ ] 11.2 评估是否让 model-compare 的人工选择协议迁移到 decision checkpoint
- [ ] 11.3 评估是否引入 blueprint 索引摘要的更细粒度自动刷新
- [ ] 11.4 评估是否为 history 建立更紧凑的 feature_key 聚合视图

说明：

- 第二阶段建立在本蓝图落地之后
- 在文档治理闭环未稳定前，不提前扩张交互能力
