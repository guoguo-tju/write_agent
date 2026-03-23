# Write Agent 验收清单（Verification Checklist）

- Version: `v1`
- Last Updated: `2026-03-22`
- Reference Spec: `docs/specs/development-spec-v1.md`

## 1. Purpose
本清单定义“改动完成后必须执行的最小验证动作”。  
默认采用分层门槛：改动范围越核心，验证越完整。

## 2. Change Classification
先判断本次改动属于哪一类（可多选）：

1. 前端改动（`frontend/**`）
2. 后端业务改动（`src/write_agent/api/**`、`src/write_agent/services/**`、`src/write_agent/models/**`）
3. 可观测/核心链路改动（`src/write_agent/observability/**`、全局异常处理、SSE 协议、trace 贯穿）
4. 仅文档改动（`README*`、`docs/**`、`docs/CHANGELOG.md`）

## 3. Mandatory Commands by Class

### 3.1 前端改动（必跑）
```bash
cd frontend && npm run build
```

### 3.2 后端业务改动（必跑）
```bash
PYTHONPATH=src uv run pytest -q <相关测试文件>
```

建议：只跑与改动直接相关的测试模块，避免无关全量耗时。

### 3.3 可观测/核心链路改动（必跑）
```bash
PYTHONPATH=src uv run pytest -q
```

说明：涉及 trace/node/behavior、SSE 事件结构、全局错误契约时，必须全量回归。

### 3.4 仅文档改动（必做）
- 校验新增链接可达（文件存在、路径正确）。
- 校验规范与 changelog 已同步更新。

## 4. Observability Contract Spot-check (Manual)
以下检查至少完成一轮：

1. 任意请求响应头包含：
- `X-Trace-Id`
- `X-Request-Id`

2. 任意错误响应包含：
- `detail`
- `error_code`
- `trace_id`
- `request_id`
- `node_id`
- `behavior_id`

3. 任意 SSE 事件包含 `obs`，且 `obs` 包含：
- `trace_id`
- `node_id`
- `behavior_id`
- `event_id`
- `ts`

4. 给定 `trace_id` 可通过：
- `GET /api/observability/traces/{trace_id}`
获得完整时间线，并可继续通过 `node_id` 反查节点映射。

## 5. Documentation Gate
若本次改动涉及“接口行为、可观测契约、验收标准”，必须同步更新：
- `docs/specs/development-spec-v1.md`（必要时）
- `docs/specs/verification-checklist.md`（必要时）
- `docs/CHANGELOG.md`

## 6. Evidence Template (for delivery notes)
提交结果建议使用以下结构：

1. 变更范围：前端/后端/可观测/文档
2. 执行命令：列出实际执行命令
3. 结果摘要：通过/失败与关键输出
4. 排障标识：若有异常，附 `trace_id` 与 `node_id`
5. 风险与后续：未覆盖项或后续建议

## 7. Pass/Fail Criteria
- 满足对应类别的必跑项，且结果通过：`PASS`
- 任一必跑项未执行或失败：`FAIL`
