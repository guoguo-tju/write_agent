# Changelog

## 2026-03-22

### Added
- 新增仓库级 AI 开发入口规范：`AGENTS.md`（强制先读 SPEC，再执行开发/验收/更新 changelog）。
- 新增全栈开发规范文档：`docs/specs/development-spec-v1.md`（覆盖架构约束、可观测性约束、兼容策略、DoD 与排障 SOP）。
- 新增分层验收清单：`docs/specs/verification-checklist.md`（定义前端/后端/核心链路的必跑验证项）。
- 新增 GitHub 仓库增强缓存模型 `GitHubRepoEnrichmentCache`（按 `repo_full_name` 唯一），并在模型导出与建库脚本中注册。
- 新增趋势改写行级构建接口：`POST /api/github-trends/rewrite/build-item`，支持后端统一产出改写预填内容与增强元数据。
- 新增前端趋势增强元类型：`GithubTrendEnrichMeta`、`GithubTrendAddMaterialResponse`、`GithubTrendRewriteBuildResponse`。
- 新增趋势回归测试：增强开关透传、改写构建接口、缓存命中与降级行为、素材增强更新幂等。
- 新增全系统可观测性模块：`observability/registry.py|context.py|emitter.py|redaction.py|errors.py|middleware.py`。
- 新增可观测检索 API：`GET /api/observability/events`、`GET /api/observability/traces/{trace_id}`、`GET /api/observability/nodes`、`GET /api/observability/nodes/{node_id}`。
- 新增可观测事件索引模型 `ObservabilityEvent` 与结构化日志落盘（`data/observability/events-YYYY-MM-DD.log`）。
- 新增可观测回归测试：`tests/test_observability_api.py`（trace 头、错误字段、SSE `obs`、检索与鉴权）。

### Changed
- `README.md` 与 `README.zh-CN.md` 新增“开发规范入口”区块，统一指向 `AGENTS.md` 与 `docs/specs/*`。
- 统一后续迭代默认流程：需求对齐 -> 对照 SPEC -> 实施改动 -> 分层机检 -> 更新 changelog。
- 行级「素材库 / 改写」接入统一“仓库增强抓取”管线，支持 `enhance` 开关（默认开启）、缓存优先与失败降级不阻断主流程。
- `POST /api/github-trends/materials/add-item` 扩展可选参数 `enhance`，返回中新增 `updated` 与 `enrich` 元数据。
- 行级「改写」从前端本地拼接改为调用后端构建，增强成功时注入结构化摘要（项目定位、核心能力、快速上手、适用场景、风险/局限、最近动态），失败时自动回退周榜基础模板。
- 趋势页新增“增强模式”开关（本地持久化），并在行级动作反馈中展示增强命中/降级状态。
- 素材库单仓库保持单条记录：已有记录在“缺增强章节”或“缓存刷新成功”时原地更新增强章节。
- API 全局接入 trace/request 贯穿：响应头统一返回 `X-Trace-Id` 与 `X-Request-Id`。
- 全局错误响应扩展为可观测结构：`error_code/trace_id/request_id/node_id/node_key/behavior_id/behavior_key`（保留 `detail`）。
- 改写/审核/工作流/封面等 SSE 事件统一携带 `obs` 元数据（`trace_id/node_id/behavior_id/event_id/ts`）。
- 核心 API 与服务链路完成节点埋点（rewrites/reviews/materials/covers/styles/github_trends + LLM/RAG/workflow/scheduler）。
- 前端错误处理支持展示可复制定位信息：`trace_id/node_id/error_code`（含 SSE 错误）。
- `dev/test` 模式启用注册表强校验（未注册节点/行为直接报错），`prod` 自动降级 `unknown_*` 并告警。
- `.env.example` 扩展 `OBS_ENABLED/OBS_MODE/OBS_LOG_DIR/OBS_RETENTION_DAYS/OBS_TOKEN/OBS_STRICT_DEV`。
- 中英文 README 补充 GitHub 趋势流程说明与页面截图（`docs/screenshots/github-trends-page-v2.png`），并在 Quick Start 增加 `GITHUB_TOKEN`（或 `GITHUB_PERSONAL_ACCESS_TOKEN`）可选配置说明。
- 中英文 README FAQ 各新增 1 条 GitHub 趋势常见问题：未配置 token 时的降级提示含义。

### Verification
- `rg -n "AGENTS.md|development-spec-v1|verification-checklist" README.md README.zh-CN.md docs/specs/*.md` 可命中全部入口链接与规范文件。
- `test -f AGENTS.md && test -f docs/specs/development-spec-v1.md && test -f docs/specs/verification-checklist.md` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_service.py tests/test_github_trends_api.py` 通过（12 passed）。
- `cd frontend && npm run build` 通过。
- `PYTHONPATH=src uv run pytest -q` 通过（74 passed）。
- `rg -n "GitHub 趋势|GitHub Trends|github-trends-page-v2\\.png|GITHUB_TOKEN|GITHUB_PERSONAL_ACCESS_TOKEN|degraded" README.zh-CN.md README.md` 可命中新增说明、截图引用、Quick Start 与 FAQ 条目。

## 2026-03-20

### Fixed
- 修复封面自动模式长时间卡在“生成 Prompt”阶段的问题：为关键词提取与封面 Prompt 生成增加超时保护（默认 12s）并自动回退本地兜底策略，避免前端持续“等待生成”。
- 修复封面本地归档异常：补齐 `src/write_agent/api/covers.py` 中缺失的 `asyncio` 导入，封面生成完成后可稳定落盘到 `./data/covers`，不再回退临时远端链接。
- 优化封面风格注入：对超长 `style_description`（尤其 JSON）进行关键字段提炼与截断，降低上游模型调用耗时与阻塞风险。

### Added
- 新增回归测试 `tests/test_cover_prompt_timeout.py`：验证 LLM 慢响应/超时时封面 Prompt 会正确走本地兜底。
- 新增回归测试 `tests/test_cover_style_description.py`：验证封面风格描述压缩逻辑（优先关键字段、避免超长噪声注入）。
- 新增 GitHub 趋势能力：后端增加 `github_trending_snapshots/github_trending_items` 两张表与 `GitHubTrendingService`，支持周榜 Top10 抓取、每日快照、周归档（周一归档上一周最终快照）。
- 新增 GitHub 趋势 API：`GET /api/github-trends`、`GET /api/github-trends/weeks`、`POST /api/github-trends/refresh`、`POST /api/github-trends/materials/add-item`、`POST /api/github-trends/materials/add-week-digest`。
- 新增前端页面 `GitHub 趋势`（`/github-trends`）：周选择器、手动更新、行级/批量入素材、行级/周汇总去改写。
- 新增回归测试 `tests/test_github_trends_service.py` 与 `tests/test_github_trends_api.py`。

### Changed
- 顶部导航增加 `GitHub 趋势` Tab（中英双语）。
- 改写页支持消费路由 `state.prefillSource`，可从趋势页“一键去改写”后自动预填源文本（不自动触发改写）。
- `main.py` 生命周期新增 GitHub 趋势内置调度器：默认 `Asia/Shanghai` 每日 `09:05` 自动抓取，支持与手动更新复用并发锁。
- `.env.example` 增加 `GITHUB_TOKEN` 与趋势调度相关配置项。

### Verification
- `PYTHONPATH=src pytest -q tests/test_cover_local_storage.py tests/test_cover_prompt_timeout.py tests/test_cover_style_description.py tests/test_cover_size_mapping.py` 通过（8 passed）。
- 手工流式验收通过：`GET /api/covers/stream?rewrite_id=23&size=2.35:1` 可返回 `done`，且 `image_url` 为本地路径 `/media/covers/...`。
- `PYTHONPATH=src pytest -q tests/test_api_regressions.py tests/test_github_trends_service.py tests/test_github_trends_api.py` 通过（29 passed）。
- `cd frontend && npm run build` 通过。
- 真实接口烟测通过：`POST /api/github-trends/refresh` 成功抓取 Top10；行级与周汇总入素材接口均返回成功，且重复调用可正确去重（`created=false`）。

## 2026-03-14

### Changed
- 中英文 README 补强“排版（`/layout`）”能力表达：项目简介、亮点段落与推荐体验路径均明确排版闭环。
- 中英文 README 将排版亮点文案统一为“公众号排版能力：按公众号格式多风格排版，并一键导出到公众号”的口径。
- 修复封面页“新建封面风格”弹窗输入控件样式：`input/textarea` 统一深色背景、边框与聚焦态，消除浅色底突兀问题。

### Verification
- 文档链接与 `layout` 关键描述已在 `README.md`、`README.zh-CN.md` 自检通过。
- 前端样式修改仅涉及 `frontend/src/pages/CoversPage.css`，未改动业务逻辑与接口。

## 2026-03-13

### Added
- 前端新增公众号排版页：`/layout`，接入 Markdown 渲染、主题切换、实时预览、富文本/图片粘贴转换、微信兼容复制。
- 新增排版入口联动：改写页、审核页、封面页均支持“去排版”，并统一携带 `rewrite_id` 跳转。
- 排版页支持按 `rewrite_id` 导入图文种子：并行拉取改写正文与封面，自动清洗 `[配图建议|...]` 占位符；无封面时给出引导提示。

### Changed
- 改写页目标长度档位扩展为 `[100, 300, 500, 800, 1000, 1500, 2000, 5000, 8000]`，默认值保持 `500`。
- 排版页改为路由级懒加载，避免将排版能力打入首页主包。
- 前端构建新增 `manualChunks` 分包策略，并将 `highlight.js` 改为 `core + 按需语言注册`，显著降低排版相关 chunk 体积。
- README 的排版页截图更新为最新 UI（替换 `docs/screenshots/layout-page-v2.png` 与 `docs/screenshots/layout-page.png`）。

### Verification
- `cd frontend && npm run build` 通过，`layout-markdown` 从约 `1072.71kB` 降至 `175.31kB`，不再触发 `>500k` chunk 告警。
- `cd frontend && npm run lint` 通过（仅剩历史 `react-hooks/exhaustive-deps` warning，无 error）。
- Playwright 端到端烟测通过：语言切换与持久化、`/layout` 路由、三处“去排版”入口跳转、`rewrite_id` 导入与无封面兜底提示均符合预期。
- 本地校验截图替换已生效：`layout-page-v2.png` 分辨率更新为 `2932x1452`。

## 2026-03-12

### Added
- 前端新增轻量 i18n 基础层（无第三方库）：`LanguageProvider`、`useLanguage()`、`messages` 字典、`formatMessage` 模板插值，语言持久化键为 `write_agent_lang`。
- 顶部导航新增全局 `CN / EN` 语言切换控件，默认中文，切换后全站即时生效并持久化。

### Changed
- 改写页目标长度档位细化为 `[100, 300, 500, 800, 1000, 1500, 2000]`，默认值从 `1000` 调整为 `500`，保持滑杆离散交互不变。
- 前端 5 个页面与顶部导航完成静态文案双语化：`Home/Styles/Materials/Reviews/Covers`。
- 公共分页组件完成双语化，英文模式下分页文案显示为 `Previous / Next / Page ...`。
- `Input`/`Textarea` 组件的随机 id 生成改为 React `useId`，移除渲染期 `Math.random` 引发的 purity lint 错误。

### Verification
- `cd frontend && npm run build` 通过。
- `cd frontend && npm run lint` 通过（仅剩历史 `react-hooks/exhaustive-deps` warning，无 error）。
- 本地联调通过：`http://127.0.0.1:5173`（前端）+ `http://127.0.0.1:8000`（后端）健康可用。
- SSE 改写实测通过：`GET /api/rewrites/stream`（`target_words=100`）完整返回 `start/progress/content/done` 并成功落库。
- 浏览器自动化验收通过：默认中文、切英文、跨 5 页面文案切换、刷新保持语言、清空 `localStorage` 恢复中文。

## 2026-03-06

### Changed
- 重构 `README.md` 与 `README.zh-CN.md` 为双语同构精简结构：流程与截图 -> 快速开始 -> 项目结构 -> FAQ -> 许可证。
- 移除 README 中冗长章节（独立技术栈细节、环境变量大段说明、运行验证长清单、贡献指南、API 明细叙述），聚焦开源项目首屏可读性与上手效率。
- 快速开始统一为“少步骤可起服务”的口径，并固定默认验收数据库为 `./data/acceptance_write_agent.db`。
- 替换 `docs/screenshots/` 下 5 张页面截图为最新 UI 版本（同名覆盖，链接路径不变）。
- 为规避 GitHub 图片缓存，README 截图链接切换到 `*-v2.png` 新文件名。
- 在中英文 README 开头补充“业务价值/项目亮点”段，并显式说明写作阶段 RAG 检索与引用展示能力及降级口径。
- 封面生成改为“本地持久化优先”：生成后自动落盘到 `./data/covers`，后端新增 `/media/covers` 静态托管，避免历史图因临时签名 URL 过期而无法显示。
- 前端封面页新增相对 `image_url` 解析逻辑，`/media/covers/...` 可在前后端不同端口时正常预览与下载。
- `.gitignore` 增加 `data/covers` 目录忽略规则，并在 README FAQ 明确“封面图片仅本地保存，不上传 GitHub”。

### Verification
- 校验中英文 README 双向跳转链接可用。
- 校验 5 张截图路径与文件存在性。
- `pytest -q tests/test_cover_local_storage.py tests/test_cover_size_mapping.py tests/test_api_regressions.py` 通过（25 passed）。
- `cd frontend && npm run build` 通过。

## 2026-03-05

### Added
- 改写页支持从素材库选择原文：新增素材选择弹窗（搜索 + 分页 + 一键填充源文本）。
- 改写页新增 RAG 引用可视化：默认开启 RAG，可配置引用条数并展示本次引用素材卡片。
- 素材页新增 RAG 检索测试区：可输入问题、设置 TopK、查看召回结果与相似度。
- 素材页新增素材支持“仅链接提交”：支持公众号/Twitter(X)/通用网页抓取正文。
- 新增素材详情编辑能力：点击素材卡片可打开弹窗查看完整内容并编辑保存。
- 后端新增 `PATCH /api/materials/{id}` 素材更新接口（含向量索引重建）。
- 后端新增 `POST /api/materials/retrieve` 素材检索测试接口。

### Changed
- 素材创建与更新在“标题为空 + 仅 URL”场景下，改为自动解析正文标题（不再默认使用 URL 作为标题）。
- 素材检索返回结果 enrich：补充 `title/source_url/tags/content/score`，并兼容缺失素材降级。
- 素材卡片与检索结果卡片修复超长文本/链接溢出样式问题。
- 改写页“源文本”区域移除“草稿 V1”文案，改为更明确的操作提示。

### Tests
- `pytest -q` 全量通过。
- `pytest -q tests/test_api_regressions.py` 通过（新增素材 URL-only、retrieve、update 回归用例）。
- `cd frontend && npm run build` 通过。
