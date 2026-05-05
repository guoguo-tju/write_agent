# Changelog

## 2026-05-05

### Changed
- 新增默认风格 seed 机制：后端启动时自动从仓库内 `src/write_agent/config/defaults/*.json` 补齐写作风格与封面风格，确保新用户拉取项目后可直接使用预置默认项。
- 默认 seed 采用“按名称补齐、已存在不覆盖”的幂等策略，避免覆盖本地用户已编辑/已删除同名风格。
- 新增默认风格数据资产：
  - 写作风格 4 条（来自本地手动录入常用项）。
  - 封面风格 5 条（封面提示词常用项）。
- 新增回归测试：覆盖 seed 初始化幂等与“同名不覆盖”行为，防止后续回归导致重复写入或误覆盖。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_default_style_seed_service.py` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_api_regressions.py -k "manual_cover_rewrite_creates_default_style_once"` 通过。

## 2026-04-08

### Changed
- GitHub 趋势简介补翻超时参数调优：单条翻译请求超时由 `4s` 调整为 `8s`，降低本地 OpenAI 兼容网关高峰抖动时的误降级概率。
- 新增回归测试：校验 `_translate_description_to_zh_single` 使用放宽后的单条超时值，避免后续回归到过短超时导致“长期待翻译”。
- GitHub 趋势中文质量判定规则放宽：允许“中文主干 + 大量英文技术名词/模型名”的翻译结果通过，修复 `system_prompts_leaks` 等条目因字母占比高被误判为“未翻译完成”的问题。
- 新增回归测试：覆盖“技术名词较多但中文主干清晰”的翻译通过，以及“几乎全英文仅夹杂少量中文”仍被拒绝。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_service.py -k "single_translation_uses_relaxed_timeout or is_acceptable_zh or refresh_retry_untranslated_only_updates_fallback_rows"` 通过。

## 2026-04-07

### Changed
- GitHub 趋势手动更新新增“补翻模式”：`POST /api/github-trends/refresh` 支持 `retry_untranslated_only=true`，可在指定 `period_key` 下仅重试未完成中文翻译条目，不再强制整榜抓取。
- GitHub 趋势补翻服务能力新增：在同周期最新成功快照上仅更新 `description_zh`，已完成中文翻译条目保持不变，避免反复刷新导致不必要重算。
- GitHub 趋势前端手动更新改为默认传入当前选中周期并启用补翻模式，优先解决“该项目英文简介暂未完成中文翻译，请稍后重试。”的遗留条目。
- GitHub 趋势简介显示修复：当项目原始英文简介为空时，中文页不再误显示“翻译未完成”，改为“暂无简介”，避免把“无源文本”误判为“翻译失败”。
- GitHub 趋势手动更新反馈优化：补翻完成后若仍有待翻译条目，前端提示会明确显示剩余条数，不再一律显示“已更新完成”。
- 新增回归用例：
  - API：校验 `retry_untranslated_only/period_key` 参数透传到服务层。
  - Service：校验补翻模式只处理未完成条目，不触发整榜抓取。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_service.py tests/test_github_trends_api.py` 通过（28 passed）。
- `cd frontend && npm run build` 失败（受既有改动影响，报错位于 `src/pages/covers/IllustrationsTab.tsx`，与本次 GitHub 趋势改动无直接关系）。
- `cd frontend && npm run build` 通过（本次前端提示修复后，产物构建成功）。

## 2026-04-05

### Changed
- GitHub 趋势日榜交互修复：当所选日期暂无成功快照并回退到最近可用快照时，日期下拉不再被回写为回退日期，保留用户所选 `requested_period_key`，避免“选 4 月 3 日自动跳回 4 月 2 日”的错觉。
- GitHub 趋势翻译稳态修复：批量翻译结果的 `index` 兼容字符串数字（如 `"0"`），避免模型返回字符串索引时被误丢弃。
- GitHub 趋势补翻策略优化：单条补翻由“全局预算”改为“逐条重试”，确保每个未命中批量翻译的条目都能获得重试机会，不再出现前几条重试、后几条直接落入中文兜底文案的情况。
- 新增 GitHub 趋势翻译回归用例：
  - 缺失批量翻译时，待翻译条目会逐条触发单条补翻（不受全局预算限制）。
  - 批量翻译响应 `index` 为字符串数字时可正确写回对应条目。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_service.py` 通过（17 passed）。
- `cd frontend && npm run build` 通过。
## 2026-03-31

### Changed
- 规范升级：`docs/specs/development-spec-v1.md` 升级到 `v1.2`，新增“热点集市中文化（MUST）”规则。
- 明确要求：中文界面下热点列表简介/摘要必须为中文；若上游为英文，后端必须走 AI 翻译/总结生成中文。
- 明确降级语义：AI 翻译失败时不得静默展示英文原文，必须返回中文降级文案，并保持可观测错误契约（`trace_id` 等）。
- GitHub 趋势中文化实现收口：日榜与周榜均执行简介中文翻译增强，不再仅周榜翻译。
- GitHub 趋势翻译失败时新增中文降级文案（`该项目英文简介暂未完成中文翻译，请稍后重试。`），前端中文界面不再回退展示英文原文。
- GitHub 趋势翻译链路超时治理：批量翻译请求超时从固定 45s 收敛为短超时，失败后直接中文降级，不再逐条长超时重试，避免刷新长期占锁导致 `409 更新中`。
- 回收本地运维脚本曝光：移除中英文 README 中 `scripts/dev_ctl.sh` 的公开说明，并将该脚本从仓库跟踪中移除（保留为本地私有运维习惯，不作为项目功能对外承诺）。

### Verification
- `rg -n "Spec Version|Last Updated|Hot Market Localization Rule|v1\\.2" docs/specs/development-spec-v1.md` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_service.py tests/test_github_trends_api.py` 通过（22 passed）。
- `cd frontend && npm run build` 通过。
- `POST /api/github-trends/refresh` (`period_type=daily`) 本地验证通过：返回 `description_zh` 为中文（示例：`开源前沿语音 AI`）。

## 2026-03-30

### Changed
- GitHub 趋势升级为“双周期”：新增 `daily/weekly` 周期语义，页面支持日榜/周榜切换、周期选择与按周期手动刷新。
- GitHub 趋势后端抓取链路支持 `daily`：调度任务改为每日同时刷新日榜与周榜，快照模型新增 `period_type/period_key` 字段并用于查询与存储隔离。
- GitHub 趋势 API 扩展周期能力（保持兼容）：`GET /api/github-trends`、`POST /api/github-trends/refresh`、行级 `add-item/build-item` 均支持 `period_type/period_key`。
- 新增 `GET /api/github-trends/periods` 周期列表接口，前端日榜下拉改用该接口拉取最近周期。
- 行级动作兼容修复：前端日榜行的“入素材/去改写”已透传周期参数，后端服务与 API 同步兼容 `daily`，避免仅传 `week_key` 的旧约束导致失败。
- GitHub 趋势文案与生成语义按周期切换：日榜显示“今日新增 Star”、周榜显示“本周新增 Star”；Top10 一键去改写标题/来源类型同步按日榜或周榜切换。
- `GithubTrendsPage.css` 去除重复样式定义块，避免同选择器重复声明造成维护冲突。

### Added
- GitHub 趋势服务回归新增：`daily` 快照字段落库、`stars today` 解析、日周期列表查询覆盖。
- GitHub 趋势 API 回归新增：`period_type=daily` 查询/刷新、`/periods` 日周期返回、行级 `add-item/build-item` 日榜请求覆盖。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_github_trends_api.py tests/test_github_trends_service.py` 通过（20 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_stream_interrupt_consistency.py` 通过（2 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（150 passed）。
- `cd frontend && npm run build` 通过。

## 2026-03-29

### Changed
- Linux.do 刷新链路新增服务端冷却窗控制：同周期刷新成功后进入可配置冷却时间，冷却命中时直接返回 429，避免短时间重复打上游。
- Linux.do RSS 抓取新增 429 自动退避重试：读取 `Retry-After`（秒值或 HTTP-date）作为退避基准，重试耗尽后按重试窗口写入冷却并返回明确限流语义。
- Linux.do 刷新 API 细化 429 语义：区分“冷却中”与“上游限流”两类场景，前端可按提示时间重试。
- 全局 HTTP 异常处理器保留业务自定义响应头（如 `Retry-After`），避免可观测包装后丢失限流重试信号。
- Linux.do 趋势摘要升级为“规则 + LLM 智能总结”双轨：当正文长度超过阈值时优先用大模型输出“短文 + 要点”摘要，失败自动回退规则截断，刷新链路仍保持可用。
- Linux.do 刷新链路新增超时治理：刷新阶段仅处理默认 `limit` 条目；topic 明细 403 回退路径不再触发 LLM，总体刷新耗时显著收敛，避免前端 60s 请求超时。
- Linux.do 智能摘要改为独立短超时调用（不复用全局 60s 超时），防止单条摘要调用拖慢整批刷新。
- Linux.do 趋势页移除“浏览/点赞”两列与其表格映射，减少无效 0 值干扰，并为核心字段释放横向空间。
- Linux.do 趋势页进一步收敛列宽：内容摘要列加宽，作者/标签列缩窄，提升 1366+ 宽度下的一屏可读性。
- Linux.do 趋势页移除“查看详情”入口与详情弹窗能力，内容摘要仅保留“预览 + 悬浮全文”交互。
- Linux.do `入素材` / `去改写` 链路新增详情降级策略：当 `topic/{id}.json` 被 403 拦截时，自动回退到榜单摘要，不再返回 500。
- Linux.do `入素材` / `去改写` 预填内容移除 `## 观察点（可补充）` 与 `## 改写提示（可补充）` 两段，避免把模板提示混入正文素材。
- Linux.do 趋势页摘要悬浮层改为无缝悬停（去除 hover 间隙），支持鼠标直接移入后滚动浏览全文，无需先点击“固定”。
- Linux.do 趋势页摘要悬浮层视觉强化：提升边框对比、增加左侧强调色与阴影层次，降低与底层正文混淆。
- README（中英）补充 Linux.do 趋势能力说明，并新增页面截图展示，首页能力清单与实际功能保持一致。
- GitHub 趋势页移除“批量加入 Top10 到素材库”按钮，减少误触入口并收敛到单条入素材/改写与“本周Top10去改写”主路径。
- GitHub 趋势表格“项目”列加宽，并恢复超长仓库名自动换行，减少项目名被截断带来的阅读成本。
- 端到端流程图热点入口语义更新：`XHS 热点` 替换为 `Linux.do 热点`，并同步更新 Mermaid 源文件与导出的 SVG 展示图。
- 流程说明文档同步口径：`docs/workflow-overview.zh-CN.md` 中的“可选热点入口”由 `GitHub/XHS` 更新为 `GitHub/Linux.do`。
- GitHub 趋势中文页简介展示补齐回退：当 `description_zh` 缺失时，优先展示原始 `description`（英文），不再直接显示“暂无简介”。
- 新增本地开发控制脚本 `scripts/dev_ctl.sh`：支持 `start/stop/restart/status/logs` 一键管理前后端进程，并统一维护 `data/backend-dev.pid`、`data/frontend-dev.pid` 与对应日志。
- 中英文 README 新增一键运维用法，降低本地联调时的启动/停止成本。

### Added
- 新增 Linux.do 回归用例：覆盖冷却窗口拦截、RSS 429 读取 `Retry-After` 后重试、429 重试耗尽后的限流返回。
- 新增 Linux.do API 回归：`/api/linuxdo-trends/refresh` 在“冷却命中/上游限流”场景统一返回 429，并携带可读重试提示。
- 新增 Linux.do 服务回归用例：`topic 详情 403` 时，`add_item_to_materials/build_item_rewrite_markdown` 仍可成功返回。
- 新增 Linux.do 配置项：`LINUXDO_SUMMARY_USE_LLM`、`LINUXDO_SUMMARY_LLM_TRIGGER_CHARS`，用于控制长摘要智能总结开关与触发阈值。
- 新增 Linux.do 配置项：`LINUXDO_SUMMARY_LLM_TIMEOUT_SECONDS`，用于限制单次智能摘要调用耗时。
- 新增 Linux.do 智能总结观测事件：`summary.llm.start/done/fallback`，可追踪触发、成功与回退原因。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_linuxdo_trends_service.py tests/test_linuxdo_trends_api.py` 通过（21 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（142 passed）。
- `curl --noproxy '*' -i -sS -X POST http://127.0.0.1:8000/api/linuxdo-trends/refresh ...` 连续触发验证：首次 `200`，冷却命中返回 `429` 且含 `retry-after` 头。
- `test -f docs/screenshots/linuxdo-trends-page-v2.png` 通过。
- `rg -n "Linux\\.do Trends|Linux\\.do 趋势页面|linuxdo-trends-page-v2\\.png" README.md docs/README.zh-CN.md` 通过。
- `cd frontend && npm run build` 通过（GitHub 趋势页按钮与列宽调整后）。
- `npx -y @mermaid-js/mermaid-cli -i docs/diagrams/write-agent-content-workflow.mmd -o docs/diagrams/write-agent-content-workflow.svg` 失败（退出码 1，触发兜底流程）。
- `curl -fsSL -X POST https://kroki.io/mermaid/svg -H 'Content-Type: text/plain; charset=utf-8' --data-binary @docs/diagrams/write-agent-content-workflow.mmd -o docs/diagrams/write-agent-content-workflow.svg` 通过。
- `file docs/diagrams/write-agent-content-workflow.svg` 返回 `SVG Scalable Vector Graphics image`。
- `rg -n "Linux\\.do 热点|write-agent-content-workflow\\.svg" docs/diagrams/write-agent-content-workflow.mmd docs/workflow-overview.zh-CN.md README.md docs/README.zh-CN.md` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_linuxdo_trends_service.py tests/test_linuxdo_trends_api.py` 通过（16 passed）。
- `cd frontend && npm run build` 通过。
- `cd frontend && npm run build` 通过（GitHub 趋势简介回退逻辑修复后）。
- `bash -n scripts/dev_ctl.sh` 通过。
- `bash scripts/dev_ctl.sh status` 通过（可输出 backend/frontend 进程与端口状态）。
- `bash scripts/dev_ctl.sh restart` 通过（重启命令链路可执行并产生日志）。
- `bash scripts/dev_ctl.sh logs all 20` 通过（可读取前后端最近日志）。
- `POST /api/linuxdo-trends/materials/add-item` 本地验证返回 `200`（topic 403 场景下已降级）。
- `POST /api/linuxdo-trends/rewrite/build-item` 本地验证返回 `200`（topic 403 场景下已降级）。
- `POST /api/linuxdo-trends/rewrite/build-item` 返回内容已确认不再包含 `## 观察点（可补充）` 与 `## 改写提示（可补充）`。
- `POST /api/linuxdo-trends/refresh` 本地压测：返回 `200`，耗时约 `23.92s`（低于前端 60s 超时阈值）。

## 2026-03-28

### Changed
- Linux.do 趋势抓取主入口由 `top.json` 切换为 `top.rss`（`weekly/monthly`），规避 Cloudflare challenge 403 导致的刷新失败。
- Linux.do 趋势新增“RSS 主榜单 + `/t/{id}.json` 明细补全”两阶段链路：榜单字段先落库，明细补作者/标签/浏览/点赞/正文摘要。
- Linux.do 刷新失败语义细化为“部分成功可用”：RSS 成功但个别 topic 明细失败时不阻断整批快照，失败条目回退 RSS 基础字段与默认统计值。
- 新增 Linux.do 趋势主链能力（Discourse JSON 公共接口）：支持 `weekly/monthly` 两种周期口径、默认 20 条返回、单标签后端过滤、最近 12 期历史回看。
- 新增 Linux.do 每日定时任务（默认 `09:10`，`Asia/Shanghai`）：每日刷新 weekly + monthly 两套快照，并沿用统一可观测事件模型。
- 热点导航重构为“热点集市”下拉：桌面支持 hover 展开，移动端支持点击展开，默认主入口落在 GitHub 趋势并新增 Linux.do 趋势入口。
- 新增 Linux.do 趋势页：7天/30天切换、历史周期选择、标签筛选、手动刷新、详情弹窗、单条入素材/去改写动作。
- Linux.do 前端 API 层补齐字段归一化映射：兼容后端返回 `topic_url/view_count/like_count/reply_count` 到页面消费字段，避免空列与详情缺失。
- 修复调度异常类型映射错误：GitHub 与 Linux.do 调度循环分别捕获各自的“刷新进行中”异常，避免日志语义与跳过策略错位。
- 文档收敛：移除 `docs/diagrams/write-agent-content-workflow.drawio`，主流程图交付统一为 `mmd + svg`，避免双轨维护带来的同步成本。
- 中文首页补齐流程图展示：`docs/README.zh-CN.md` 新增 `./diagrams/write-agent-content-workflow.svg` 嵌入，与英文 `README.md` 保持一致。
- 规范治理升级：`docs/specs/development-spec-v1.md` 升级为 `v1.1`，新增“主链路语义变化必须同步更新 Mermaid/SVG 流程图”的 MUST 规则，并将流程图同步纳入 DoD（未同步视为未完成）。
- 验收清单升级：`docs/specs/verification-checklist.md` 升级为 `v1.1`，新增 `3.5 主链路变更附加验收`（文件存在、README 引用、mmdc 导出、kroki 兜底、SVG 类型校验）。
- `README.md` 首页新增 `docs/diagrams/write-agent-content-workflow.svg` 展示入口，确保主流程图在 GitHub 首页可见并纳入可达性校验。
- 重绘 `docs/diagrams/write-agent-content-workflow.drawio` 视觉样式：改为分区泳道布局（输入来源/改写审核闭环/封面排版/可观测排障）、统一深色科技风卡片与分支连线配色，提升演示可读性与美观度。
- 将流程图进一步升级为「科技发布会风」演示版：强化舞台感标题、霓虹高对比色与主分支粗线连结，提升投屏场景下的视觉冲击与远距可读性。

### Added
- 新增后端 Linux.do 模块：
  - 路由：`/api/linuxdo-trends`、`/api/linuxdo-trends/periods`、`/api/linuxdo-trends/refresh`、`/api/linuxdo-trends/topics/{topic_id}`、`/api/linuxdo-trends/materials/add-item`、`/api/linuxdo-trends/rewrite/build-item`
  - 服务：`src/write_agent/services/linuxdo_trending_service.py`
  - 模型：`linuxdo_trending_snapshots`、`linuxdo_trending_items`
- 新增 Linux.do 可观测注册节点（API / Service / Scheduler 全链路），并保持错误响应 `trace_id` 契约。
- 新增 Linux.do 前端页面与样式：`frontend/src/pages/LinuxDoTrendsPage.tsx`、`frontend/src/pages/LinuxDoTrendsPage.css`。
- 新增 Linux.do 前端 API/类型/i18n 接线与导航入口，形成 GitHub + Linux.do 双趋势入口。
- 新增 Linux.do 回归测试：`tests/test_linuxdo_trends_service.py`、`tests/test_linuxdo_trends_api.py`。
- 新增独立流程图文档 `docs/workflow-overview.zh-CN.md`，沉淀「内容生产主链」单总图讲解版本（中文业务词命名，适配面试讲解与团队沟通）。
- 新增 Mermaid 总流程图：覆盖可选热点入口（GitHub/XHS）、改写与主编审核闭环、封面来源双分支（目标文章/手动标题正文）与排版输出链路。
- 新增 draw.io 展示版文件 `docs/diagrams/write-agent-content-workflow.drawio`，采用深色科技风并与 Mermaid 语义对齐。
- 新增 Mermaid 源文件 `docs/diagrams/write-agent-content-workflow.mmd` 与导出图 `docs/diagrams/write-agent-content-workflow.svg`，用于投屏与外部分享。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_linuxdo_trends_service.py tests/test_linuxdo_trends_api.py` 通过（12 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（133 passed）。
- `cd frontend && npm run build` 通过。
- `rg -n "write-agent-content-workflow\\.svg" README.md docs/README.zh-CN.md` 通过。
- `test ! -f docs/diagrams/write-agent-content-workflow.drawio` 通过。
- `rg -n "Workflow Diagram Sync Rule|主链路变更附加验收|write-agent-content-workflow\\.mmd|v1\\.1" docs/specs/development-spec-v1.md docs/specs/verification-checklist.md` 通过。
- `test -f docs/diagrams/write-agent-content-workflow.mmd && test -f docs/diagrams/write-agent-content-workflow.svg` 通过。
- `rg -n "write-agent-content-workflow\\.svg" README.md` 通过。
- `npx -y @mermaid-js/mermaid-cli -i docs/diagrams/write-agent-content-workflow.mmd -o docs/diagrams/write-agent-content-workflow.svg` 失败（退出码 1，触发兜底流程）。
- `test -f docs/workflow-overview.zh-CN.md && test -f docs/diagrams/write-agent-content-workflow.drawio` 通过。
- `rg -n "GitHub 热点|XHS 热点|启动改写任务|主编审核|手动标题\\+正文|trace_id" docs/workflow-overview.zh-CN.md` 通过。
- `rg -n "GitHub 热点|XHS 热点|启动改写任务|主编审核|手动封面|trace_id" docs/diagrams/write-agent-content-workflow.drawio` 通过。
- `curl -fsSL -X POST https://kroki.io/mermaid/svg -H 'Content-Type: text/plain; charset=utf-8' --data-binary @docs/diagrams/write-agent-content-workflow.mmd -o docs/diagrams/write-agent-content-workflow.svg` 通过。
- `file docs/diagrams/write-agent-content-workflow.svg` 返回 `SVG Scalable Vector Graphics image`。

## 2026-03-27

### Changed
- 封面页新增“内容来源”切换：支持“目标文章”与“手动输入”，手动输入模式可直接填写标题与正文生成封面。
- 手动输入模式支持与原有一致的三种生成模式（自动、风格匹配、自定义），并保持原 `/api/covers` 与 `/api/covers/stream` 协议兼容。
- 自动封面 Prompt 生成新增标题主锚点策略：优先参考标题，正文作为补充上下文；LLM 超时兜底 Prompt 同步纳入标题优先语义。
- 手动输入场景下，自定义 Prompt 会自动追加标题/正文摘要上下文（追加而非覆盖）。
- 封面 SSE 事件新增可选字段 `source_mode`（`manual|rewrite`），前端兼容解析。

### Added
- 新增后端接口 `POST /api/covers/manual-rewrite`：接收 `title/content`，自动复用或创建默认风格 `手动输入`，并创建 `rewrite_id` 返回给前端复用后续封面链路。
- 手动输入创建的 rewrite 采用“标题 + 正文摘要”入库策略：`source_article=title`，`final_content=content_excerpt`（最多 1200 字），状态直接置为 `completed`。
- 可观测新增节点注册：`API.COVERS.MANUAL_REWRITE`。
- 新增回归测试：手动 rewrite 创建成功、默认风格复用、标题/正文长度校验、标题优先兜底 Prompt 校验。

### Verification
- `PYTHONPATH=src uv run pytest -q tests/test_cover_prompt_template.py tests/test_cover_prompt_timeout.py tests/test_api_regressions.py -k "manual_cover_rewrite or generate_prompt_falls_back_when_llm_is_slow or render_style_prompt"` 通过（5 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_api_regressions.py tests/test_cover_prompt_template.py tests/test_cover_prompt_timeout.py` 通过（31 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（121 passed）。
- `cd frontend && npm run build` 通过。

## 2026-03-26

### Fixed
- 修复小红书热点发布时间解析缺口：`cornerTagInfo.publish_time` 现在支持相对时间与中文日期表达（如 `昨天 17:21`、`前天`、`MM-DD`），避免刷新成功但列表被 7 天窗口误过滤为 0 条。
- `cornerTagInfo` 发布时间统一复用 `_parse_publish_time` 解析链路，减少 MCP 返回格式轻微变化导致的漏数风险。
- 修复 workflow job SSE 回放标记错误：`/api/reviews/workflow/jobs/{job_id}/stream` 现在会将订阅建立前的历史事件正确标记为 `is_replay=true`，仅实时新增事件标记为 `false`。
- 修复审核流 detached 实体异常：`review_service` 完成阶段不再因 `ReviewRecord` 脱离 Session 导致 `Instance is not bound to a Session`，避免“本应 done 却落 error”。
- 修复 stale 恢复 detached 异常：`resume_stale_jobs` 不再在提交后读取脱离 Session 的对象属性，避免恢复队列阶段抛错中断。

### Changed
- 小红书热点列表新增 `content` 字段：后端统一按“原文不超过 500 字直接返回，超过 500 字压缩为 500 字内摘要”产出，旧缓存数据自动回退为标题兜底。
- 热点表格在“标题”后新增“内容”列，默认两行截断展示；鼠标悬停/聚焦时显示小弹窗查看完整内容摘要。
- 详情补拉（`xhs_get_note_detail`）阶段新增正文提取，命中时可回填更完整的内容摘要。
- 前端导航临时隐藏“热点选题”Tab（保留路由可直达），用于对外演示阶段降低未成熟功能暴露。
- 新增“XHS 测试期静默运行”文档：中英文 README 增加 `login -> start -> status/logs -> stop` 运维流程与常见故障排查。
- `.env.example` 补充本地 MCP 运维层可选变量说明：`XHS_MCP_NPX_PACKAGE`、`XHS_MCP_PORT`、`XHS_ENABLE_LOGGING`、`XHS_HEADLESS`（仅脚本读取，不影响应用配置解析）。
- 改写工作流升级为 V2 任务化链路：新增异步任务执行与 SSE 订阅能力（job 创建、状态查询、事件流、恢复、取消），并保留旧 `POST /api/reviews/workflow` 桥接兼容。
- 改写/审核流在中断场景新增终态收敛兜底：流被中断后不再长期残留 `running`，会自动落为 `failed` 并写入标准错误信息。
- LLM 客户端新增统一超时配置：`OPENAI_TIMEOUT_SECONDS`（默认 `60s`），降低上游长时间无响应导致单 worker 长阻塞风险。
- 应用生命周期新增运行期 stale-job 恢复巡检循环（默认每 15 秒），不再仅依赖“启动时恢复”。

### Added
- 新增回归测试：覆盖 `algovate_mcp` 返回 `cornerTagInfo=[{"type":"publish_time","text":"昨天 17:21"}]` 时，刷新后可正常入库并在热点列表可见。
- 新增回归测试：覆盖内容摘要规则（短文本直出、超长文本压缩、空内容标题兜底）及 API `content` 字段返回。
- 新增本地运维脚本 `scripts/xhs_mcp_ctl.sh`，支持 `login | start | stop | status | logs`，默认固定 `xhs-mcp@0.8.11` 且 `start` 走静默 headless 常驻。
- 新增工作流任务持久化模型：`workflow_jobs`、`workflow_job_events`、`rewrite_chunks`，支持 checkpoint、事件重放与分片落库。
- 新增工作流任务 API：`POST /api/reviews/workflow/jobs`、`GET /api/reviews/workflow/jobs/{job_id}`、`GET /api/reviews/workflow/jobs/{job_id}/stream`、`POST /api/reviews/workflow/jobs/{job_id}/resume`、`POST /api/reviews/workflow/jobs/{job_id}/cancel`、`GET /api/reviews/workflow/jobs/by-rewrite/{rewrite_id}`。
- 新增前端任务化接入：`runWorkflowWithStream` 先创建 job 再订阅 stream，并在已存在 `rewrite_id` 且状态为 `running` 时自动尝试续连最近任务。
- 新增回归测试：覆盖工作流任务 API 幂等键复用、任务状态语义、任务流 SSE 结构与旧接口桥接兼容。
- 新增回归测试：覆盖 workflow job `is_replay` 回放标记语义、stale-job 恢复重排队语义、review 流完成阶段 detached 异常回归。
- 新增系统性验收测试矩阵：业务逻辑单测（路由条件/评分阈值）、接口端到端回归（正常/降级/失败/人工介入）、Prompt 快照回归（base/revision）、流式并发中断一致性回归。
- 新增测试文件：`tests/test_acceptance_api_matrix.py`、`tests/test_prompt_snapshot.py`、`tests/test_stream_interrupt_consistency.py`、`tests/snapshots/rewrite_prompt_base.txt`、`tests/snapshots/rewrite_prompt_revision.txt`。

### Verification
- `env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY NO_PROXY=127.0.0.1,localhost PYTHONPATH=src uv run pytest -q tests/test_xhs_trends_service.py` 通过（18 passed）。
- `env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY NO_PROXY=127.0.0.1,localhost PYTHONPATH=src uv run pytest -q tests/test_xhs_trends_api.py` 通过（8 passed）。
- 本地联调验证：`POST /api/xhs-trends/refresh` 返回 `errors={}`，随后 `GET /api/xhs-trends?category_key=tech&sort=hot&limit=5` 返回 `items_count=5`。
- `env -u http_proxy -u https_proxy -u all_proxy -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY NO_PROXY=127.0.0.1,localhost PYTHONPATH=src uv run pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py` 通过（26 passed）。
- `cd frontend && npm run build` 通过。
- `bash -n scripts/xhs_mcp_ctl.sh` 通过。
- `XHS_MCP_PORT=3011 bash scripts/xhs_mcp_ctl.sh start && XHS_MCP_PORT=3011 bash scripts/xhs_mcp_ctl.sh status && XHS_MCP_PORT=3011 bash scripts/xhs_mcp_ctl.sh logs 20 && XHS_MCP_PORT=3011 bash scripts/xhs_mcp_ctl.sh stop && XHS_MCP_PORT=3011 bash scripts/xhs_mcp_ctl.sh status` 通过（脚本全链路验证通过）。
- `bash scripts/xhs_mcp_ctl.sh status` 通过（默认 `3000` 端口下可识别现有 xhs-mcp 监听与 `/health` 状态）。
- `test -x scripts/xhs_mcp_ctl.sh && rg -n "xhs_mcp_ctl\\.sh|XHS_MCP_NPX_PACKAGE|XHS_HEADLESS|XHS_ENABLE_LOGGING" .env.example README.md docs/README.zh-CN.md` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_api_regressions.py tests/test_observability_api.py` 通过（32 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_workflow_service.py` 通过（12 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（103 passed）。
- `cd frontend && npm run build` 通过。
- `PYTHONPATH=src uv run pytest -q tests/test_workflow_service.py tests/test_review_service.py -k "stream_events_marks_replay or stream_events_only_marks_new_rows_as_live or detached_error or resume_stale_jobs_requeues_running_jobs"` 通过（4 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_workflow_service.py tests/test_api_regressions.py tests/test_observability_api.py` 通过（47 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（107 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_review_service.py tests/test_workflow_service.py -k "below_threshold or at_threshold or retry_boundary or zero_max_retries"` 通过（4 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_acceptance_api_matrix.py` 通过（4 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_prompt_snapshot.py` 通过（2 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_stream_interrupt_consistency.py` 通过（2 passed）。
- `PYTHONPATH=src uv run pytest -q` 通过（119 passed）。

## 2026-03-25

### Changed
- 主 API 路由重新接入 `xhs_trends` 后端模块，`/api/xhs-trends*` 重新恢复可达。
- 小红书热点补齐可观测节点注册：API、服务、SSE 事件与刷新状态查询均可通过 strict registry 校验。
- 小红书热点刷新互斥升级为同主机跨进程文件锁，仍保留分类粒度与现有内存锁兜底。
- 评论补拉新增“最近富化冷却”TTL，避免重复对近期已富化笔记再次拉取详情。
- MCP HTTP 调用改为复用长连接会话与会话 ID，避免每次调用都重新执行初始化握手。
- `.env.example` 的 XHS 配置精简为“最小暴露”模式：默认仅保留 `XHS_TRENDS_PROVIDER` 与 `XHS_MCP_URL`，其余参数改为代码默认值或按需注释启用。
- 小红书热点刷新链路改为“分层批量”策略：`refresh` 仅做列表聚合入缓存，评论详情补拉改为异步阶段执行，降低同步刷新的外部调用峰值。
- `POST /api/xhs-trends/refresh` 默认按“当前分类”执行（未传 `category_key` 时回退首个分类），并发命中同分类刷新时返回 `status=in_progress`。
- 新增分类级刷新互斥，避免同分类重复刷新导致的请求放大与缓存覆盖竞争。
- `http_api` 且缺少 `XHS_TRENDS_API_BASE_URL` 时不再伪成功，改为返回明确错误并写入 `fetch_error`。
- XHS 外链安全收敛：后端对 `source_url` 做 `http/https` 白名单清洗；前端渲染前再做一次协议校验，非法链接显示 `--`。
- 前端热点页修复分类/排序切换竞态：仅接受最新请求结果，切换时失效旧轮询与旧分析流，避免“旧数据回写”。
- `.env.example` 与设置项更新：`XHS_TRENDS_COMMENT_DETAIL_LIMIT` 默认降至 `3`，新增详情补拉节流与重试参数（`XHS_MCP_DETAIL_*`）。
- MCP 解析补强：`structuredContent.success=false` 视为失败，空结果改为显式错误，避免静默清空数据。

### Added
- 新增 `POST /api/xhs-trends/refresh/status` 查询接口，用于查看当前分类刷新锁状态与最近评论富化状态。
- 新增回归测试覆盖：同分类并发刷新互斥、详情补拉限流重试、配置缺失错误语义、非法链接清洗、refresh `in_progress` 契约。
- 新增回归测试覆盖：跨实例刷新互斥、评论富化 TTL 跳过、MCP 会话复用、刷新状态 API。

### Verification
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src /Library/Frameworks/Python.framework/Versions/3.10/bin/pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py` 通过（24 passed）。
- `PYTHONPATH=src uv run pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py`
- `PYTHONPATH=src uv run pytest -q`
- `cd frontend && npm run build`

## 2026-03-24

### Changed
- 小红书热点服务新增 provider 分支：`algovate_mcp`（默认）与 `http_api`（兼容保留），`/api/xhs-trends*` 前后端接口路径与主交互保持不变。
- `refresh` 流程切换为“分类关键词聚合 -> 去重标准化 -> 7天窗口与互动门槛过滤 -> hot/latest 排序 -> 热门条目补拉详情评论”。
- 新增 xhs MCP 配置项并写入配置体系：`XHS_TRENDS_PROVIDER`、`XHS_MCP_URL`、`XHS_MCP_TIMEOUT_SECONDS`、`XHS_MCP_BROWSER_PATH`。
- 分类配置支持 `keywords`，默认 5 类均预置 5 个检索词，缺省时回退为分类名。
- 可观测注册新增节点 `SVC.XHS_TRENDS.MCP_CALL`，MCP 调用开始/成功/失败均产生日志事件并带错误码。
- 刷新失败语义增强：`refresh.errors` 现在可返回真实失败原因（如 `xhs-mcp` 不可达、未登录），并保持缓存降级可读。
- MCP 预检容错增强：`xhs_auth_status` 返回 `StatusCheckError` 时不再直接阻断刷新流程，改为记录告警后继续拉取真实列表。
- MCP SSE 解码链路修复：优先按 UTF-8 解码 `text/event-stream`，并优化 fallback 反转义流程，修复中文标题乱码。
- 本地预览调优：`XHS_MCP_TIMEOUT_SECONDS` 上调为 60 秒；本机 `.env` 临时设置 `XHS_TRENDS_LOOKBACK_DAYS=30` 以便小红书真实数据可视化验证（默认规范值仍为 7 天）。
- 小红书刷新接口支持后台触发：`POST /api/xhs-trends/refresh` 新增请求字段 `background`（默认 `false`），`background=true` 时立即返回 `status=accepted` 并在后台执行刷新，避免前端 60s 超时阻断交互。
- 热点页新增自动预取逻辑：首次进入或切分类且无数据时，自动触发后台批量预取并轮询当前分类数据，减少用户手动刷新操作。
- 抓取动作可配置降噪：新增 `XHS_TRENDS_MAX_KEYWORDS_PER_CATEGORY`、`XHS_TRENDS_COMMENT_DETAIL_LIMIT`，支持降低单次刷新调用量，减少 `xhs-mcp` 频繁弹窗与超时概率。
- 缓存降级显示优化：在 `http_api` provider 且无 base_url 的缓存回退路径中，清理历史 `fetch_error` 提示，避免长期显示陈旧错误。

### Added
- 新增 `tests/test_xhs_trends_service.py` 的 MCP 路径回归覆盖：关键词聚合去重、评论补拉、不可用降级缓存与 stale 状态断言。
- 新增 MCP 容错与解码回归测试：`StatusCheckError` 不阻断刷新、SSE 中文内容 UTF-8 解码不乱码。
- 新增 API 回归：`/api/xhs-trends/refresh` 背景模式返回契约测试（`status=accepted`）。

### Verification
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src .venv/bin/pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py` 通过（11 passed）。
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src .venv/bin/pytest -q` 通过（85 passed）。
- `cd frontend && npm run build` 通过。
- `PYTHONPATH=src .venv/bin/pytest -q tests/test_xhs_trends_service.py -k "transient_status_check_error or extract_text_payload_from_sse_keeps_chinese_text or decode_mcp_http_payload_uses_utf8_for_sse"` 通过（3 passed）。
- `curl --noproxy '*' -sS -X POST "http://127.0.0.1:8000/api/xhs-trends/refresh" -H "Content-Type: application/json" -d '{"category_key":"tech"}'` 返回 `refreshed_categories=["tech"]`。
- `curl --noproxy '*' -sS "http://127.0.0.1:8000/api/xhs-trends?category_key=tech&sort=hot&limit=5"` 返回 `item_count=5`，标题中文正常显示。
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src .venv/bin/pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py` 通过（15 passed）。
- `cd frontend && npm run build` 通过。

## 2026-03-23

### Changed
- 仓库根目录瘦身：将 `README.zh-CN.md` 下沉至 `docs/README.zh-CN.md`，将 `CHANGELOG.md` 下沉至 `docs/CHANGELOG.md`，减少首页文件噪音。
- 根 `README.md` 的中文文档入口更新为 `docs/README.zh-CN.md`。
- 中文 README 迁移后统一修正相对路径：English 入口、截图链接、规范入口链接均调整为 `docs/` 内可达路径。
- 开发规范文档同步更新 changelog 路径约定：`AGENTS.md`、`docs/specs/development-spec-v1.md`、`docs/specs/verification-checklist.md` 改为引用 `docs/CHANGELOG.md`。
- 新增根目录 `LICENSE`（MIT 正文），并将中英文 README 的许可证改为可点击链接，同时补充 MIT 徽章。
- 新增小红书热点能力（`/api/xhs-trends`）：支持分类查询、分类热点列表、手动刷新、分类分析 SSE 流。
- 新增「热点选题」独立前端 Tab（`/hot-topics`）：分类切换、热度/最新排序、10 条热点展示、自动分析与 `trace_id` 排障提示。
- 小红书热点遵循固定规则：近 7 天窗口、最小互动门槛 100、热度公式 `like*1.0 + favorite*0.8 + comment*0.5`。
- 可观测注册表新增 xhs 相关节点：API 入口、SSE 事件与服务链路（categories/get/refresh/analyze）。
- `.env.example` 扩展 `XHS_TRENDS_*` 配置项，默认分类配置文件落位 `src/write_agent/config/xhs_trends_categories.json`。

### Added
- 新增后端服务 `src/write_agent/services/xhs_trends_service.py`，实现第三方授权数据抓取、缓存、排序过滤、规则/LLM 混合分析。
- 新增后端路由 `src/write_agent/api/xhs_trends.py`，并接入主 API Router。
- 新增前端页面 `frontend/src/pages/XhsTrendsPage.tsx` 与样式 `frontend/src/pages/XhsTrendsPage.css`。
- 新增前端类型与 API 封装：`XhsTrendItem`、`XhsTrendListResponse`、`XhsTrendAnalysisSseEvent`、`XhsInspirationCard`、`XhsCommentTopic`。
- 新增分类配置文件 `src/write_agent/config/xhs_trends_categories.json`（默认 5 类：科技/职场/美食/情感/个人成长）。
- 新增回归测试：`tests/test_xhs_trends_service.py`、`tests/test_xhs_trends_api.py`。

### Verification
- `test -f docs/README.zh-CN.md && test -f docs/CHANGELOG.md` 通过。
- `test ! -f README.zh-CN.md && test ! -f CHANGELOG.md` 通过。
- `rg -n "README\\.zh-CN\\.md|CHANGELOG\\.md" README.md AGENTS.md docs/specs/*.md docs/README.zh-CN.md` 可命中更新后的新路径引用。
- `test -f LICENSE && rg -n "License: MIT|\\(\\./LICENSE\\)|\\(\\.\\./LICENSE\\)" README.md docs/README.zh-CN.md` 通过。
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src .venv/bin/pytest -q tests/test_xhs_trends_service.py tests/test_xhs_trends_api.py` 通过（8 passed）。
- `env -u ALL_PROXY -u all_proxy -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy PYTHONPATH=src .venv/bin/pytest -q` 通过（82 passed）。
- `cd frontend && npm run build` 通过。

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
