# GitHub 趋势页「日榜 + 周榜」设计说明

- Date: `2026-03-30`
- Status: `Draft for Review`
- Owner: `Write Agent`

## 1. 背景与目标
当前 GitHub 趋势页仅支持周榜（`week_key`），无法满足“天级趋势观察 + 周级趋势沉淀”的双视角需求。

本设计目标：
1. 在现有 GitHub 趋势页新增 `日榜/周榜` 双榜能力。
2. 保持默认体验与现状一致（默认周榜）。
3. 日榜支持最近 7 天回看。
4. 定时任务每天自动刷新时，同时覆盖日榜与周榜。
5. 在向后兼容前提下完成接口与前端升级。

## 2. 已确认产品口径（冻结）
1. 日榜支持最近 7 天可切换回看。
2. 页面默认展示周榜。
3. 定时任务每天一次，同时抓取日榜 + 周榜。
4. 日榜模式下批量改写按钮文案与行为改为“今日日榜 Top10 去改写”。

## 3. 方案对比与选型

### 方案 A（采用）：双轨并行增量改造
- 思路：保留周榜主路径不破坏，在现有 GitHub 趋势模块内增量引入日榜能力。
- 优点：兼容风险最低、上线速度快、回归范围可控。
- 缺点：服务层会出现少量 `period_type` 分支。

### 方案 B：统一 period 抽象重构
- 思路：把现有 `week_key` 全量重构为 `period_type + period_key` 通用模型。
- 优点：长期结构最整洁。
- 缺点：改动面过大，当前阶段上线风险高。

### 方案 C：日榜旁路缓存
- 思路：周榜走现有数据库，日榜走独立缓存文件。
- 优点：开发快。
- 缺点：一致性差、可观测与维护成本高，不适合正式能力。

结论：采用方案 A。

## 4. 范围与非范围

### In Scope
1. GitHub 趋势 API/Service/前端页面新增日榜能力。
2. GitHub 调度任务支持每日双轨刷新。
3. 可观测节点与行为注册补齐。
4. 相关测试与文档更新。

### Out of Scope
1. Linux.do/XHS 页面行为变更。
2. GitHub 趋势抓取源替换。
3. 对“改写工作流”链路做业务重构。

## 5. 数据模型设计

### 5.1 现状
- `github_trending_snapshots` 目前以 `week_key + snapshot_date` 唯一。
- `github_trending_items` 通过 `snapshot_id` 关联。

### 5.2 目标模型（增量）
在 `github_trending_snapshots` 新增：
1. `period_type`：`weekly | daily`
2. `period_key`：
   - 周榜：`YYYY-Www`
   - 日榜：`YYYY-MM-DD`

兼容策略：
1. 历史数据回填：`period_type=weekly`，`period_key=week_key`。
2. 保留 `week_key` 字段，作为兼容读取与已有调用方兜底。
3. 新增唯一约束：`period_type + period_key + snapshot_date`。

说明：`github_trending_items` 表不需要结构变更，继续复用。

## 6. 后端服务设计

### 6.1 抓取层
新增/扩展抓取方法：
1. 周榜抓取：`https://github.com/trending?since=weekly`
2. 日榜抓取：`https://github.com/trending?since=daily`

解析兼容：
1. 保持 Top10 条目抓取逻辑。
2. star 文案解析同时兼容 `this week` 与 `today`，失败时回退数字提取。

### 6.2 快照持久化
统一保存入口按 `period_type` 落库：
1. `refresh_snapshot(period_type)`
2. `get_snapshot(period_type, period_key?)`
3. `list_available_periods(period_type)`

行为约束：
1. `weekly` 维持当前语义。
2. `daily` 只返回最近 7 天可选项（按 `period_key` 倒序）。

### 6.3 调度
在现有每日调度 tick 中顺序执行：
1. 先刷新 `daily`
2. 再刷新 `weekly`

失败处理：
1. 两个子任务分别记录成功/失败事件。
2. 单个失败不阻断另一个刷新尝试。

## 7. API 与兼容策略

### 7.1 查询接口
- 现有：`GET /api/github-trends?week_key=...`
- 增强：支持可选参数
  - `period_type=daily|weekly`（默认 `weekly`）
  - `period_key=...`

兼容规则：
1. 未传 `period_type` 时，完全按现有周榜逻辑。
2. 传 `period_type=weekly` 时，`period_key` 与 `week_key` 都可解析（`period_key` 优先）。
3. 传 `period_type=daily` 时，使用 `period_key=YYYY-MM-DD`。

### 7.2 周期列表接口
- 新增：`GET /api/github-trends/periods?period_type=daily|weekly`
- 保留：`GET /api/github-trends/weeks`（兼容旧前端）

### 7.3 刷新接口
- 现有：`POST /api/github-trends/refresh`
- 增强：可选 body `period_type`，默认 `weekly`。

### 7.4 入素材与去改写
- 保持原接口不破坏。
- 增加对 `period_type + period_key` 的识别；旧 `week_key` 继续可用。

## 8. 前端交互设计

### 8.1 顶部控制区
新增榜单切换：`日榜 | 周榜`。

1. 周榜模式
- 展示周选择器（现有逻辑）。
- 批量按钮文案：`本周Top10去改写`。

2. 日榜模式
- 展示最近 7 天日期选择器。
- 批量按钮文案：`今日日榜Top10去改写`。

### 8.2 默认行为
1. 页面初始默认周榜。
2. 手动刷新刷新当前榜单类型。
3. 错误提示与 trace_id 展示沿用现有规范。

## 9. 可观测性设计（按 SPEC）
新增节点/行为并注册到 `observability/registry.py`：
1. `API.GITHUB_TRENDS.PERIODS`
2. `SVC.GITHUB_TRENDS.REFRESH_DAILY`
3. `SVC.GITHUB_TRENDS.GET_DAILY`
4. `JOB.GITHUB_TRENDS.SCHEDULER_DAILY`

要求：
1. API 入口使用 `obs_scope(...)`。
2. 错误响应保留 `trace_id/request_id/node_id/behavior_id`。
3. 调度链路发射 daily/weekly 分段事件，便于定位哪一段失败。

## 10. 测试与验收

### 10.1 业务单测
1. `period_type` 路由分支正确。
2. 日榜 `period_key` 格式校验与最近 7 天裁剪正确。
3. 日榜/周榜抓取 URL 与解析分流正确。
4. star 文案（today/week）解析回归。

### 10.2 接口回归
1. 周榜旧参数调用不回归。
2. 日榜查询、日榜刷新、周期列表正常。
3. 手动刷新冲突（409）与失败流语义正确。

### 10.3 异常与一致性
1. 定时任务 daily 失败、weekly 成功时状态可区分。
2. 并发刷新时互斥语义保持一致。
3. 错误响应可带 `trace_id` 排障。

### 10.4 命令门槛
1. `PYTHONPATH=src uv run pytest -q <github_trends 相关测试>`
2. 若触及可观测核心契约，执行 `PYTHONPATH=src uv run pytest -q`
3. `cd frontend && npm run build`

## 11. 风险与缓解
1. GitHub 页面文本变化导致解析不稳。
- 缓解：双模式正则 + 数字回退提取 + 解析失败监控事件。

2. 迁移脚本影响历史查询。
- 缓解：幂等迁移；保留旧字段与旧接口。

3. 前后端参数双轨期可能混用。
- 缓解：服务端统一归一化参数优先级并补充回归。

## 12. 发布与回滚
1. 发布后默认周榜，不影响现有用户路径。
2. 日榜异常时可快速降级：前端隐藏日榜切换，后端继续保周榜。
3. 回滚策略：按 API/前端双开关逐步回退，不删历史数据。

## 13. 自检结果（Spec Self-Review）
1. Placeholder 扫描：无 `TODO/TBD` 占位项。
2. 一致性检查：口径与接口、调度、前端行为一致。
3. 范围检查：聚焦 GitHub 趋势日/周榜，不扩展其他模块。
4. 歧义检查：默认榜单、刷新策略、日榜回看范围已明确。
