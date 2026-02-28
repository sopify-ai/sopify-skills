---
name: model-compare
description: Multi-model compare sub-skill; triggers only on `~compare <question>` or `对比分析：<question>`; runs configured models in parallel and asks user to choose.
---

# Model Compare (MVP) - Runtime-Converged Rules

**Goal:** Run the same prompt across multiple configured models in parallel, show normalized results, and let the user choose manually.

---

## Trigger Conditions (exactly two)

```yaml
1) Command prefix: ~compare <question>
2) Natural-language prefix: 对比分析：<question>
```

All other inputs (such as `~go` and regular Q&A) do not trigger this skill.

---

## Entry Wiring (`~compare` / `对比分析：`)

- After trigger, the entry must call `run_model_compare_runtime(...)` from `scripts/model_compare_runtime.py`
- Runtime chain is fixed: extract -> redact -> truncate -> shared payload -> fan-out -> normalize
- `context_bridge` defaults to `true`; `false` must stay in bypass mode (question-only input)
- If context pack is empty (`facts=0` and `snippets=0`), fallback reason must include `context_pack empty`
- Output must include metadata: `bridge/files/snippets/redactions/truncated`

> Documentation convergence: execution-level details use `scripts/model_compare_runtime.py` as the single source of truth (SSOT). This skill keeps only entry and output contracts.

---

## Configuration Loading

Read from `sopify.config.yaml`:

```yaml
multi_model:
  enabled: true|false
  trigger: manual
  timeout_sec: 25
  max_parallel: 3
  include_default_model: true|false # optional, default true
  context_bridge: true|false # optional, default true; single bypass switch
  candidates:
    - id: glm
      enabled: true
      provider: openai_compatible
      base_url: https://...
      model: glm-4.7
      api_key_env: GLM_API_KEY
```

**Switch semantics (keep two layers):**
- `multi_model.enabled`: top-level feature gate; `false` means no multi-model fan-out
- `multi_model.candidates[*].enabled`: per-candidate participation switch
- `multi_model.include_default_model`: include the current session default model as a candidate; defaults to `true` when omitted (no extra config required)
- `multi_model.context_bridge`: context bridge bypass switch; defaults to `true` when omitted. `true` uses the runtime bridge pipeline; `false` sends question-only input (emergency bypass)

**MVP constraints:**
- Support only `provider: openai_compatible`
- API keys must be loaded from environment variables via `api_key_env`
- Never expose plaintext keys in config output or logs

---

## Execution Flow (Entry Layer)

```
1. Parse user question (strip "~compare " or "对比分析：" prefix)
2. Load multi_model config and apply defaults: include_default_model=true, context_bridge=true
3. Build runtime arguments:
   - `question` (normalized question text)
   - `multi_model_config` (raw config)
   - `default_candidate` (session default model candidate)
   - `model_caller` (callout callback)
4. Call `run_model_compare_runtime(...)` for unified runtime output
5. If `mode=fanout`: output A/B/C... and wait for manual selection; if `mode=single`: output single-model result with fallback reasons
6. Output line must include context metadata: `bridge/files/snippets/redactions/truncated`
```

---

## Runtime Convergence (Code Is Source of Truth)

- Implementation file: `scripts/model_compare_runtime.py`
- Main entry: `run_model_compare_runtime(...)`
- Defaulted flags: `include_default_model=true`, `context_bridge=true`
- Hard budgets: `max_files=6`, `max_snippets=10`, `max_lines_per_snippet=160`, `max_chars_total=12000`
- Fixed contracts: empty-pack fallback reason `context_pack empty`, metadata `bridge/files/snippets/redactions/truncated`

---

## Result and Failure Policy

**First response handling:**
- If one model returns early, mark it as `done`
- Keep waiting for remaining models until all done or timeout
- Do not end the compare round early

**Failure isolation:**
- One model timeout/failure must not block others
- If at least one model succeeds, continue with manual selection
- If all fail, return a compact error summary and ask user to check config/env vars

**No-config fallback:**
- If `multi_model` is missing, `enabled=false`, `candidates` is empty, or all keys are unavailable
- Do not throw an error; fallback to single-model response
- Clearly state in output that compare mode was not entered

**Fallback reason details (required in `~compare` output):**
- Output a "Fallback reasons" list with at least one specific reason
- Consistent wording rule: prefer **reason code** output (optional readable text can be appended), recommended codes:
  - `FEATURE_DISABLED: multi_model.enabled=false`
  - `NO_ENABLED_CANDIDATES: candidates[*].enabled=true count=0`
  - `UNSUPPORTED_PROVIDER: id={candidate_id}, provider={provider}`
  - `MISSING_API_KEY: candidate_id={candidate_id}`
  - `DEFAULT_MODEL_UNAVAILABLE: include_default_model=true`
  - `CONTEXT_BRIDGE_BYPASSED: context_bridge=false`
  - `CONTEXT_PACK_EMPTY: facts=0 snippets=0`
  - `INSUFFICIENT_USABLE_MODELS: {usable_count}<2`

---

## Security and Logging

- Redact sensitive values in logs: `api_key`, `token`, `cookie`, passwords, secret connection strings
- Never print actual environment variable values
- Log only necessary metadata: model id, latency, status, and optional short error reason

---

## Output Format

```
[{BRAND_NAME}] Q&A ✓

Model comparison complete: {success_count}/{total_count}
Context bridge: {enabled|disabled (bypass)}
Context pack: files={N}, snippets={N}, redactions={N}, truncated={true|false}
Selectable results: A({model_id}) / B({model_id}) / C({model_id})
Hint: Reply "Pick A" or "Pick B" to continue

---
Changes: 0 files
Next: Please choose one result (e.g. Pick A)
```

**Single-model fallback output example:**

```
[{BRAND_NAME}] Q&A !

Compare mode not entered; executed in single-model mode.
Fallback reasons:
- INSUFFICIENT_USABLE_MODELS: 1<2
Result: {single_model_result}

---
Changes: 0 files
Next: Adjust multi_model.enabled / candidates[*].enabled / include_default_model / context_bridge or provide missing env vars
```
