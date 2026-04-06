# 插图 Tab（SVG 生成）设计方案

- 日期: 2026-04-06
- 状态: Draft for Review
- 关联页面: `frontend/src/pages/CoversPage.tsx`（新增二级 Tab）
- 关联主链路: 改写 -> 审核 -> 封面/插图 -> 排版

## 1. 背景与目标

当前改写结果中已经会插入配图建议占位：

`[配图建议|名称:一句话命名|说明:适合配图的画面描述]`

但现状仅停留在文本建议，排版导入时会清理占位符，缺失“建议 -> 可用插图资产 -> 文章预览”的闭环。

本次目标是在封面页旁新增 `插图` Tab，支持基于现有配图建议逐条生成 SVG（并派生 PNG），并在页面右侧看到与全文排版结合的即时效果。

## 2. 已确认范围（In Scope）

1. 在封面页增加二级 Tab：`封面 | 插图`。
2. 插图来源仅来自改写正文中的 `[配图建议|...]`，本次不支持手动新增插图条目。
3. 逐条手动触发生成，支持多条并发，系统并发上限 `3`。
4. 每条卡片支持编辑 `名称`、`说明`、切换风格（信息图/流程图/轻插画）。
5. 右侧全文预览：
   - 已生成槽位显示图片（PNG）。
   - 未生成槽位保留原始 `[配图建议|...]` 文本。
6. 存储策略：每张图生成成功立即落库（不等待“应用全部”）。
7. 资产策略：保存 SVG 源，同时自动派生 1080px 宽 PNG（公众号/排版使用）。
8. 风格默认判定：纯 LLM 分类；分类失败/超时回退 `信息图`。
9. 非法 SVG 处理：自动重试 1 次，仍失败则该条置 `failed`。
10. 发版门禁新增人工真链路实操（每次发版必跑），证据文档位置：`docs/releases/<date>-illustration-smoke.md`。

## 3. 非目标（Out of Scope）

1. 不做插图条目的手动新增、拖拽排序、位置锚定编辑。
2. 不做版本历史、A/B 比较、批量一键全生成。
3. 不做独立“插图库管理页”。
4. 不改变改写正文原文内容（预览按映射替换，不回写正文）。

## 4. 用户流程（MVP）

1. 用户在改写/审核链路拿到 `rewrite_id`。
2. 打开封面页，切换到 `插图` Tab。
3. 系统解析该 `rewrite_id` 的 `final_content`，提取插图槽位列表。
4. 用户在左侧编辑某条的 `名称/说明`，可手动改风格。
5. 点击“生成 SVG”，该条进入 `generating`。
6. 后端按风格执行生成链路，成功后保存 `svg_content + png_url`。
7. 右侧全文预览中对应占位立即替换为生成图。
8. 用户可继续并发生成其他槽位（总并发 <= 3）。

## 5. 前端交互设计

### 5.1 页面结构

- 一级页面保持 `CoversPage`。
- 在配置区域顶部新增二级 Tab：
  - `封面`（沿用现有功能）
  - `插图`（新功能）
- 插图 Tab 采用左右分栏：
  - 左栏：插图条目列表
  - 右栏：全文预览

### 5.2 左栏卡片字段与操作

每条卡片字段：
- 槽位序号（slot_index）
- `名称`（可编辑）
- `说明`（可编辑）
- 风格选择：`信息图 | 流程图 | 轻插画`
- 状态：`pending | generating | completed | failed`
- 操作：`生成SVG`、`重试`（失败后）
- 进度文案（SSE）
- 错误摘要 + `trace_id`（失败后）

### 5.3 并发与状态

- 允许不同槽位并发生成。
- 同一槽位生成中禁止重复提交。
- 页面维护 `slot_key -> request_state` 映射，每条独立 SSE 通道。
- 并发超限时前端展示可重试提示，不阻塞其他已在运行任务。

### 5.4 右栏全文预览

- 预览渲染基于“正文 + 槽位映射”。
- 遇到占位符：
  - 有可用 `png_url` 则渲染图片。
  - 无图片则显示原始 `[配图建议|...]` 文本。

## 6. 后端设计

### 6.1 数据模型

新增表：`illustration_records`

字段建议：
- `id: int PK`
- `rewrite_id: int`（FK -> `rewrite_records.id`）
- `slot_index: int`（占位在正文中的顺序）
- `slot_key: str`（稳定键）
- `name: str`
- `description: str`
- `style: str`（`infographic|flowchart|lite_illustration`）
- `style_source: str`（`llm|fallback|user`）
- `prompt: str | null`
- `svg_content: str | null`
- `png_url: str | null`
- `status: str`（`pending|generating|completed|failed`）
- `error_message: str | null`
- `created_at: datetime`
- `updated_at: datetime`

唯一性建议：
- `(rewrite_id, slot_index)` 做唯一约束（每槽位仅保留最新有效记录）。

### 6.2 API 设计

1. `GET /api/illustrations/rewrite/{rewrite_id}/slots`
- 作用：实时解析配图建议并合并已保存记录。
- 返回：槽位列表（含当前建议文本、已有生成状态与资源）。

2. `GET /api/illustrations/stream`
- Query: `rewrite_id, slot_index, name, description, style?`
- 作用：SSE 流式生成单条插图。
- 事件建议：`start/progress/classify/generate/svg_validating/png_rendering/saving/done/error`

3. `GET /api/illustrations/by-rewrite?rewrite_id=...`
- 作用：读取该改写已有插图记录（用于快速恢复页面状态）。

### 6.3 生成编排

- 风格分类（仅当未传 `style`）：
  - LLM 分类到三选一。
  - 超时/失败 -> `infographic`。

- 流程图：
  - LLM 生成 Mermaid 文本。
  - Mermaid 转 SVG。

- 信息图/轻插画：
  - LLM 直接输出 SVG。

- SVG 质量门：
  - 结构合法校验。
  - 安全清洗（禁脚本、禁外链、禁危险标签）。
  - 失败自动重试 1 次。

- PNG 派生：
  - 固定导出宽度 `1080px`。

- 成功即落库：
  - `status=completed`
  - 写入 `svg_content + png_url`。

## 7. 可观测与错误契约

遵循仓库 `development-spec-v1.md`：

1. 新 API 入口使用 `obs_scope(...)`。
2. SSE 事件统一 `attach_obs_meta(...)`。
3. 新 node/behavior 注册到 `src/write_agent/observability/registry.py`。
4. 错误响应包含：
   - `detail/error_code/trace_id/request_id/node_id/node_key/behavior_id/behavior_key`

## 8. 验收与测试方案

## 8.1 自动化测试（接口/服务）

1. 槽位解析
- 能正确提取所有 `[配图建议|...]`。
- 顺序与 `slot_index` 一致。

2. 风格分类
- 正常分类。
- 超时/失败回退 `infographic`。

3. 生成链路
- `flowchart` 走 Mermaid->SVG。
- `infographic/lite_illustration` 走 LLM->SVG。

4. SVG 异常处理
- 非法 SVG 自动重试 1 次。
- 二次失败落 `failed` 并带错误信息。

5. 并发控制
- 并发 <= 3 时可并行成功。
- 超过 3 的请求得到明确限流语义。

6. 落库一致性
- 成功记录必须同时存在 `svg_content` 与 `png_url`。

7. 可观测契约
- SSE 事件有 `obs`。
- 错误响应有完整排障字段。

## 8.2 浏览器 E2E 自动化

1. Happy Path
- 从改写结果进入插图 Tab。
- 并发生成多条。
- 右侧预览逐步替换对应槽位。

2. 错误恢复
- 人造非法 SVG 触发重试与失败提示。

3. 分类兜底
- 人造分类超时，回退 `infographic`。

4. 并发上限
- 第 4 条任务提示超限可重试。

## 8.3 人工真链路验收（每次发版必跑）

每次发版必须由执行人完整操作一次：

1. 生成一篇带配图建议的改写文章。
2. 进入插图 Tab，至少触发 2 条并发生成。
3. 观察生成中、成功、失败（如有）状态是否可恢复。
4. 检查右侧全文预览替换是否正确。
5. 跳转排版页检查最终效果可用。

证据输出：
- 文档：`docs/releases/<date>-illustration-smoke.md`
- 内容包含：
  - 操作步骤
  - 关键截图
  - 命令输出摘要
  - 异常与恢复结论
  - `trace_id` 列表

## 9. 实施分期

1. M1（后端）
- 模型、API、服务编排、SSE、并发限制、SVG/PNG 管线。

2. M2（前端）
- 插图 Tab、左右分栏、卡片编辑、并发状态管理、预览替换。

3. M3（验证与文档）
- 自动化回归 + E2E + 人工真链路。
- 更新 `docs/CHANGELOG.md`。
- 若主链路语义变更，更新流程图 `mmd/svg`。

## 10. 风险与缓解

1. SVG 质量不稳定
- 通过模板约束 + 校验 + 单次自动重试降低失败率。

2. 并发导致资源压力
- 后端并发上限 `3` + 明确限流反馈。

3. 预览与排版表现差异
- 强制 PNG 作为排版落地资产，SVG 仅作为源资产保留。

4. 长文槽位多导致操作成本高
- 首期维持手动逐条；后续再评估批量生成功能。

## 11. 决策摘要

- 采用方案 A（MVP 先行）。
- 数据来源仅解析改写占位符，不做手动新增。
- 支持并发生成（上限 3）。
- 生成成功即保存，资产双存（SVG + 1080 PNG）。
- 发版必须包含人工真链路验收并沉淀证据。
