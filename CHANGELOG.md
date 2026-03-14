# Changelog

## 2026-03-14

### Changed
- 中英文 README 补强“排版（`/layout`）”能力表达：项目简介、亮点段落与推荐体验路径均明确排版闭环。
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
