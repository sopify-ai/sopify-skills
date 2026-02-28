---
name: model-compare
description: 多模型对比子技能；仅在 `~compare <问题>` 或 `对比分析：<问题>` 触发；按配置并发调用多个模型并提供人工选择。
---

# 模型对比（MVP）- 运行时收口规则

**目标：** 对同一输入并发调用多个已配置模型，统一展示结果，交给用户人工选择。

---

## 触发条件（仅两种）

```yaml
1) 命令前缀: ~compare <问题>
2) 自然语言前缀: 对比分析：<问题>
```

其他输入（如 `~go`、普通问答）不触发本技能。

---

## 入口接线（~compare / 对比分析：）

- 触发后必须调用 `scripts/model_compare_runtime.py` 的 `run_model_compare_runtime(...)`
- 运行时链路固定为：抽取 -> 脱敏 -> 截断 -> 统一请求 -> 并发调用 -> 结果归一化
- `context_bridge` 未配置按 `true` 处理；`false` 必走旁路（仅问题文本）
- 若上下文包为空（`facts=0` 且 `snippets=0`），必须按 `context_pack empty` 降级
- 输出必须带元信息：`bridge/files/snippets/redactions/truncated`

> 文档收口：执行层细节以 `scripts/model_compare_runtime.py` 为单一事实来源（SSOT），本文件只保留入口契约与展示契约。

---

## 配置读取

从 `sopify.config.yaml` 读取：

```yaml
multi_model:
  enabled: true|false
  trigger: manual
  timeout_sec: 25
  max_parallel: 3
  include_default_model: true|false # 可选，默认 true
  context_bridge: true|false # 可选，默认 true；单旁路开关
  candidates:
    - id: glm
      enabled: true
      provider: openai_compatible
      base_url: https://...
      model: glm-4.7
      api_key_env: GLM_API_KEY
```

**开关语义（保留双层）：**
- `multi_model.enabled`：功能总开关；`false` 时不进入多模型并发
- `multi_model.candidates[*].enabled`：候选参与开关；仅控制该候选是否参与
- `multi_model.include_default_model`：是否将“当前会话默认模型”加入候选；未配置时默认 `true`（无需额外配置）
- `multi_model.context_bridge`：上下文桥接旁路开关；未配置时默认 `true`。`true` 使用运行时桥接链路，`false` 仅发送问题文本（应急旁路）

**MVP 约束：**
- 仅支持 `provider: openai_compatible`
- API Key 只从环境变量读取（`api_key_env`）
- 不允许在配置或输出中暴露明文 key

---

## 执行流程（入口侧）

```
1. 解析问题文本（去掉 "~compare " 或 "对比分析：" 前缀）
2. 读取 multi_model 配置，并补齐默认值：include_default_model=true, context_bridge=true
3. 构造运行时参数：
   - `question`（清洗后的问题）
   - `multi_model_config`（原始配置）
   - `default_candidate`（当前会话默认模型候选）
   - `model_caller`（模型调用回调）
4. 调用 `run_model_compare_runtime(...)` 获取统一结果
5. 若返回 `mode=fanout`：输出 A/B/C... 并等待人工选择；若 `mode=single`：直接输出单模型结果与“降级原因明细”
6. 输出行必须包含上下文元信息：`bridge/files/snippets/redactions/truncated`
```

---

## 运行时收口（以代码为准）

- 实现文件：`scripts/model_compare_runtime.py`
- 主入口：`run_model_compare_runtime(...)`
- 配置默认值：`include_default_model=true`、`context_bridge=true`
- 固定预算：`max_files=6`、`max_snippets=10`、`max_lines_per_snippet=160`、`max_chars_total=12000`
- 固定契约：空包降级原因 `context_pack empty`、统一元信息 `bridge/files/snippets/redactions/truncated`

---

## 结果与失败策略

**先返回处理：**
- 某模型先返回时，仅标记为 `done`
- 继续等待其他模型，直到全部完成或超时
- 不提前结束整轮对比

**失败隔离：**
- 单模型失败/超时不影响其他模型输出
- 至少 1 个模型成功时，仍可进入人工选择
- 全部失败时，返回错误摘要并提示检查配置/环境变量

**无配置降级：**
- 若 `multi_model` 未配置、`enabled=false`、`candidates` 为空或 key 全缺失
- 不报错，自动回退到单模型回答
- 在输出中明确提示：本次未进入多模型并发，已按单模型执行

**降级原因明细（~compare 输出必须包含）：**
- 输出“降级原因”列表，至少包含 1 条明确原因
- 口径统一：优先输出 **reason code**（可选追加中文说明），推荐 code：
  - `FEATURE_DISABLED: multi_model.enabled=false`
  - `NO_ENABLED_CANDIDATES: candidates[*].enabled=true count=0`
  - `UNSUPPORTED_PROVIDER: id={candidate_id}, provider={provider}`
  - `MISSING_API_KEY: candidate_id={candidate_id}`
  - `DEFAULT_MODEL_UNAVAILABLE: include_default_model=true`
  - `CONTEXT_BRIDGE_BYPASSED: context_bridge=false`
  - `CONTEXT_PACK_EMPTY: facts=0 snippets=0`
  - `INSUFFICIENT_USABLE_MODELS: {available_count}<2`

---

## 安全与日志

- 日志中脱敏：`api_key`、`token`、`cookie`、密码、私密连接串
- 输出中不打印环境变量实际值
- 仅记录必要元信息：模型 id、耗时、状态、错误摘要（可选）

---

## 输出格式

```
[{BRAND_NAME}] 咨询问答 ✓

模型对比完成: {success_count}/{total_count}
上下文桥接: {开启|关闭(旁路)}
上下文包: files={N}, snippets={N}, redactions={N}, truncated={true|false}
可选结果: A({model_id}) / B({model_id}) / C({model_id})
提示: 回复“选A”或“选B”继续

---
Changes: 0 files
Next: 请输入你的选择（如：选A）
```

**单模型降级输出示例：**

```
[{BRAND_NAME}] 咨询问答 !

未进入多模型并发，已按单模型执行。
降级原因:
- INSUFFICIENT_USABLE_MODELS: 1<2
结果: {single_model_result}

---
Changes: 0 files
Next: 可调整 multi_model.enabled / candidates[*].enabled / include_default_model / context_bridge 或补齐环境变量
```
