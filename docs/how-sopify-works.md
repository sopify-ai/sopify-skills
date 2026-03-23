# Sopify 如何工作

## 设计来源：Harness Engineering

Sopify 借鉴 harness engineering 的设计思路，但不把它作为仓库首页定位。这里说明的是设计来源，不是产品口号。

| Harness 原则 | Sopify 落地 |
|-------------|-------------|
| Structured Knowledge | `.sopify-skills/blueprint/` + `plan/` 分层知识库 |
| Mechanical Constraints | `manifest.json` + runtime gate + execution gate |
| Observability | `state/current_handoff.json` + checkpoint contract |
| Self-Healing / Continuity | clarification / decision / develop checkpoint resume |

`Agent Cross-Review` 当前不是 Sopify 的主承诺，因此不纳入这份 public workflow 文档。

官方参考：[`Harness engineering: leveraging Codex in an agent-first world`](https://openai.com/zh-Hans-CN/index/harness-engineering/)

## 主工作流

```mermaid
flowchart TD
    A["用户输入"] --> B["Runtime Gate"]
    B --> C{"路由判定"}
    C --> D["咨询问答"]
    C --> E["模型对比"]
    C --> F["回放 / 复盘"]
    C --> G["代码任务"]
    D --> L["输出 + handoff"]
    E --> L
    F --> L
    G --> H{"复杂度判定"}
    H --> I["快速修复"]
    H --> J["轻量迭代"]
    H --> K["完整三阶段"]
    subgraph three ["需求分析 → 方案设计 → 开发实施"]
        K1["需求分析"] --> K2["方案设计"] --> K3["开发实施"]
    end
    K --> K1
    I --> L
    J --> L
    K3 --> L
    L --> M[".sopify-skills/state/"]
```

工作流要点：

- 每次进入 Sopify 前都先经过 runtime gate
- 只有代码任务才进入复杂度分流
- 标准主链路优先依赖 handoff contract，而不是猜测 `Next:` 文案

## Checkpoint 暂停与恢复

```mermaid
flowchart TD
    A["需求分析"] --> B{"缺少事实信息?"}
    B -->|是| C["answer_questions"]
    C --> C1["展示 missing facts / questions"]
    C1 --> C2["用户补充信息"]
    C2 --> A
    B -->|否| D["方案设计"]
    D --> E{"存在设计分叉?"}
    E -->|是| F["confirm_decision"]
    F --> F1["展示选项 + 推荐项"]
    F1 --> F2["用户确认"]
    F2 --> D
    E -->|否| G["开发前确认"]
    G --> H["confirm_execute"]
    H --> H1["展示任务 / 风险 / 缓解"]
    H1 --> H2["用户回复 继续 / next / 开始"]
    H2 --> I["开发实施"]
```

Checkpoint 规则：

- `answer_questions` 用于补事实，不提前物化正式 plan
- `confirm_decision` 用于拍板分叉，确认后再恢复默认 runtime 入口
- `confirm_execute` 位于方案设计与开发实施之间，不属于开发阶段内部子步骤

## 目录结构与层级

```text
.sopify-skills/
├── blueprint/                   # L1 长期蓝图（git tracked）
│   ├── README.md
│   ├── background.md
│   ├── design.md
│   └── tasks.md
├── plan/                        # L2 活跃方案（默认 ignored）
│   ├── _registry.yaml
│   └── YYYYMMDD_feature/
├── history/                     # L3 已归档方案（默认 ignored）
│   ├── index.md
│   └── YYYY-MM/
├── state/                       # 运行态 machine truth（始终 ignored）
│   ├── current_handoff.json
│   ├── current_run.json
│   ├── current_decision.json
│   ├── current_clarification.json
│   └── sessions/<session_id>/...   # 并发 review 隔离
├── user/
│   └── preferences.md
└── project.md
```

层级说明：

- `blueprint/` 承载长期知识与稳定契约
- `plan/` 保存当前工作方案，不等同于长期蓝图
- `history/` 只存已收口方案
- `state/` 是宿主与 runtime 交接的机器事实层

## 附录：Plan 生命周期

```mermaid
flowchart LR
    A["~go / ~go plan"] --> B["plan/YYYYMMDD_feature/"]
    B --> C["活动执行"]
    C --> D["~go finalize"]
    D --> E["刷新 blueprint 索引"]
    D --> F["清理 state / 当前活动态"]
    D --> G["history/YYYY-MM/ 归档"]
    G --> H["history/index.md"]
```

附录只用于说明维护者视角的收口过程；普通用户理解主工作流即可。
