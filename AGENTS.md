# Write Agent AI Development Entry (Mandatory)

本文件是本仓库 AI 迭代的强制入口规范。任何进入本仓库执行开发任务的 AI，都必须先读取并遵守以下文档。

## 1. Required Reading Order (MUST)
1. `docs/specs/development-spec-v1.md`
2. `docs/specs/verification-checklist.md`
3. `docs/CHANGELOG.md`（最新日期条目）

## 2. Default Execution Order (MUST)
1. 理解需求与影响范围（前端/后端/可观测性）。
2. 对照 `development-spec-v1.md` 确认约束（尤其 observability 与兼容性）。
3. 实施改动（遵循分层与接口契约）。
4. 按 `verification-checklist.md` 执行分层验收。
5. 更新 `docs/CHANGELOG.md` 并记录验证结果。

## 3. Hard Constraints (MUST NOT)
- 不得新增或改动 API/SSE 行为而缺失可观测编号（`node_id/behavior_id`）。
- 不得输出缺少 `trace_id` 的可观测错误响应。
- 不得做破坏性接口变更且不提供迁移说明。
- 不得跳过规定的分层验收就宣称完成。

## 4. Observability Fast Rules (MUST)
- 新 API 入口必须使用 `obs_scope(node_key, behavior_key)`。
- 新 SSE 事件必须使用 `attach_obs_meta(...)` 注入 `obs`。
- 新节点/行为必须注册到 `src/write_agent/observability/registry.py`。
- 错误响应必须符合全局可观测字段契约（见 SPEC）。

## 5. Source of Truth
- 详细规范：`docs/specs/development-spec-v1.md`
- 机检清单：`docs/specs/verification-checklist.md`

如与历史文档冲突，以上述两份规范文档与当前代码实现为准。
