# Write Agent 全栈开发规范 SPEC（v1）

- Spec Version: `v1`
- Last Updated: `2026-03-22`
- Status: `Active`
- Owners: `Write Agent Maintainers`

## Brief Summary
本规范用于统一 Write Agent 的前后端与可观测性迭代方式。目标是让后续 AI 和人工开发都能按同一套规则开发、验收、排障，避免“各自发挥”导致的回归和定位困难。

本规范采用：
- 文档权威 + 可机检清单（非 CI 强阻断）
- 默认向后兼容
- 分层验收门槛
- trace_id/node_id 驱动的排障流程

## Problem Statement
当前系统已具备可观测基础能力（`trace_id/request_id + node_id/behavior_id + observability API`），但缺少统一、可执行、可追责的开发规范。  
没有规范时，常见问题是：
- 新功能缺少一致埋点，故障难定位；
- 前后端接口改动缺乏兼容策略，容易引入回归；
- 验收标准不一致，质量不可预测；
- 遇到线上异常时排障路径不统一，效率低。

## Scope
- 代码范围：`frontend`、`src/write_agent`、可观测体系（middleware/registry/emitter/api）。
- 适用对象：后续 AI 迭代与人工开发。
- 本期不做：新增运行时能力、重构既有架构、改变线上接口行为。

## Source of Truth
优先级从高到低：
1. 运行中代码契约（当前实现）
2. 本文档（`development-spec-v1.md`）
3. 验收清单（`verification-checklist.md`）
4. 其他说明文档（README、历史计划文档等）

其中可观测编号权威来源为：
- `src/write_agent/observability/registry.py`

## Architecture Rules

### Backend Rules
- 必须遵循 `API -> Service -> Model` 分层。
- API 层负责协议与参数校验，不堆业务实现。
- Service 层负责业务编排与状态迁移。
- Model 层负责数据结构与持久化定义。
- 新增环境变量时，必须同步更新 `.env.example`。

### Frontend Rules
- 前端调用后端接口必须通过 `frontend/src/services/api.ts` 统一封装。
- 新增或变更接口字段时，必须同步更新：
  - `frontend/src/types/index.ts`
  - 调用处页面类型使用
- 新页面或新交互文案必须同步 i18n（`frontend/src/i18n/messages.ts`）。

## Observability Rules (MUST)

### Entry and Scope
- 新 API 入口必须使用 `obs_scope(node_key, behavior_key)`。
- 新服务关键节点必须在合适粒度发 `emit_obs_event(...)`。

### Node/Behavior Registration
- 新节点或行为模式必须先注册到 `registry.py`。
- 开发/测试环境必须通过严格校验（未注册应失败）。
- 不允许长期依赖 `unknown_*` 降级路径。

### SSE Contract
- SSE 事件必须通过 `attach_obs_meta(...)` 注入 `obs`。
- `obs` 至少包含：
  - `trace_id`
  - `request_id`
  - `node_id`
  - `node_key`
  - `behavior_id`
  - `behavior_key`
  - `event_id`
  - `ts`

### Error Contract
- 错误响应必须保留 `detail`，并补充：
  - `error_code`
  - `trace_id`
  - `request_id`
  - `node_id`
  - `node_key`
  - `behavior_id`
  - `behavior_key`
- HTTP 响应头必须返回：
  - `X-Trace-Id`
  - `X-Request-Id`

### Redaction
- 事件 `payload` 必须经过脱敏策略（`redaction.py`）。
- 禁止把完整正文、prompt、token 等敏感信息直接写入可观测存储。

## API Compatibility Policy
- 默认策略：向后兼容（Additive First）。
- 允许新增字段，禁止直接删除/改语义已有字段。
- 若必须做破坏性变更，必须同时提供：
  - 迁移说明
  - 影响范围
  - 过渡策略（双轨或开关）
  - 验收与回滚方案

## Frontend Contract
- 用户可见错误必须展示 `trace_id`；若有 `node_id/error_code`，应一并展示。
- 需要可复制排障标识（至少 `trace_id`）。
- SSE 错误与普通 HTTP 错误都必须遵循同一可观测提示标准。

## Testing & Verification
- 验收采用分层门槛（详见 `verification-checklist.md`）：
  - 后端改动：相关测试最小集必须通过。
  - 核心链路/观测层改动：全量 `pytest` 必须通过。
  - 前端改动：`frontend` build 必须通过。
- 若改动涉及接口或行为契约，必须补对应回归测试。

## Incident SOP (MUST)
收到“功能不符合预期”时，按以下固定流程排查：
1. 从前端错误提示或响应头获取 `trace_id`。
2. 调 `GET /api/observability/traces/{trace_id}` 获取时间线。
3. 识别异常节点 `node_id`。
4. 调 `GET /api/observability/nodes/{node_id}` 映射到 `module_path/function_name`。
5. 结合同 trace 上下游事件与 `error_code` 定位根因。
6. 在修复说明中回填：`trace_id + node_id + root cause + fix`。

目标：从报错到定位代码位置，5 分钟内完成首轮定位。

## Definition of Done
以下五项全部满足，任务才算完成：
1. 代码实现完成（功能/行为达成）。
2. 可观测性完整（埋点、SSE `obs`、错误字段、编号注册）。
3. 验收通过（按分层清单执行并记录结果）。
4. 文档更新（必要时更新规范/README）。
5. `docs/CHANGELOG.md` 更新（含 Verification）。

## Important Public API / Interface Changes
本规范本身不新增运行时 API。  
本规范固定并要求遵守的公共契约包括：
- 响应头：`X-Trace-Id`、`X-Request-Id`
- 错误体字段：`detail/error_code/trace_id/request_id/node_id/node_key/behavior_id/behavior_key`
- SSE `obs` 字段：`trace_id/request_id/node_id/node_key/behavior_id/behavior_key/event_id/ts`
- 可观测检索 API：
  - `GET /api/observability/events`
  - `GET /api/observability/traces/{trace_id}`
  - `GET /api/observability/nodes`
  - `GET /api/observability/nodes/{node_id}`

## Test Cases and Scenarios
1. 入口可达：从 `AGENTS.md` 可跳转到本规范与机检清单。
2. 规则可执行：按清单完成前端与后端各一类验收。
3. 排障可落地：给定 `trace_id` 能定位到 `node_id -> module/function`。
4. 兼容性有效：破坏性改动若无迁移说明应判定不合规。
5. 可观测完整：关键 SSE 与错误响应字段符合契约。

## Assumptions and Defaults
1. 执行力度：文档 + 可机检清单（非 CI 强阻断）。
2. 落点：根目录 `AGENTS.md` + `docs/specs`。
3. 验收：分层门槛。
4. 接口策略：默认向后兼容。
5. 排障：trace/node 五分钟定位为必做。
6. 治理：版本化维护 + 变更记录。

## Spec Governance
- 每次修改规范，必须更新：
  - `Spec Version`
  - `Last Updated`
  - 下方 `Change Log`
- 重大规则变化必须写“迁移影响”。
- 规范变更后，相关入口文档（`AGENTS.md` / README 链接）必须保持可达。

## Change Log
- `v1` (2026-03-22): 首次建立全栈开发规范，覆盖架构、可观测性、兼容性、验收与排障流程。
