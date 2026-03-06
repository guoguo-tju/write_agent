# Changelog

## 2026-03-06

### Changed
- 重构 `README.md` 与 `README.zh-CN.md` 为双语同构精简结构：流程与截图 -> 快速开始 -> 项目结构 -> FAQ -> 许可证。
- 移除 README 中冗长章节（独立技术栈细节、环境变量大段说明、运行验证长清单、贡献指南、API 明细叙述），聚焦开源项目首屏可读性与上手效率。
- 快速开始统一为“少步骤可起服务”的口径，并固定默认验收数据库为 `./data/acceptance_write_agent.db`。
- 替换 `docs/screenshots/` 下 5 张页面截图为最新 UI 版本（同名覆盖，链接路径不变）。
- 为规避 GitHub 图片缓存，README 截图链接切换到 `*-v2.png` 新文件名。
- 在中英文 README 开头补充“业务价值/项目亮点”段，并显式说明写作阶段 RAG 检索与引用展示能力及降级口径。

### Verification
- 校验中英文 README 双向跳转链接可用。
- 校验 5 张截图路径与文件存在性。

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
