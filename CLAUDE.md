# 项目配置

## 项目概览

- **项目名**：Write Agent
- **项目定位**：面向内容创作场景的全栈 AI 写作工作台，覆盖改写、审核、封面、排版与热点选题到写作的闭环。
- **核心目标**：把“素材检索 → 风格改写 → 审核反馈 → 人工润色 → 封面生成 → 排版发布”流程产品化、可回放、可观测。
- **当前版本**：后端 `0.1.0`（见 `pyproject.toml`），前端 `0.0.0`（见 `frontend/package.json`）。

## 架构文档

@AGENTS.md  
@docs/specs/development-spec-v1.md  
@docs/specs/verification-checklist.md  
@docs/CHANGELOG.md

> 说明：本仓库已有 `AGENTS.md` 作为 AI 开发强制入口；本文件用于补齐项目级长期协作规范与快速落地手册。

## 项目简介

Write Agent 是一个 **FastAPI + React/Vite** 的全栈应用，主要能力包括：

1. 改写：输入原文并按风格与目标字数生成新稿。
2. 审核：支持主编审核与闭环重写（含失败回路）。
3. 素材库/RAG：沉淀素材并在改写时检索引用。
4. 封面：生成公众号风格封面，支持流式进度。
5. 排版：将正文/封面导入排版页用于发布准备。
6. 热点入口：GitHub Trends、Linux.do Trends（含回填到素材与改写）。

## 技术栈

### 后端

- **语言**：Python 3.10+
- **框架**：FastAPI
- **AI 编排**：LangChain、LangGraph
- **数据访问**：SQLModel + SQLAlchemy
- **服务启动**：Uvicorn
- **关键能力**：全链路 observability（trace_id / node_id / behavior_id）、SSE 流式返回、定时刷新任务（GitHub/Linux.do 趋势）

### 前端

- **语言**：TypeScript
- **框架**：React 19 + React Router 7 + Vite 7
- **UI/样式**：Tailwind CSS 4、Framer Motion、CSS
- **网络层**：Axios + fetch(SSE)
- **国际化**：`frontend/src/i18n/messages.ts`（中英双语）

### 数据与外部依赖

- **默认数据库**：SQLite（`data/acceptance_write_agent.db`）
- **向量/素材相关**：本地 data 目录（见 README）
- **模型与外部服务**：OpenAI 兼容接口、Volcengine（封面）、SiliconFlow（可选 RAG）、GitHub API（可选 Token 增强）

### 认证与部署

- **用户认证/权限系统**：当前代码中未见完整账号鉴权体系（**待确认**）
- **容器化与 CI/CD**：仓库未发现 Dockerfile / docker-compose / GitHub Actions（**待确认**）

## 核心目录结构

- `src/write_agent/main.py`：FastAPI 入口、全局异常、CORS、调度任务注册。
- `src/write_agent/api/`：HTTP 路由层（styles/materials/rewrites/reviews/covers/trends/observability）。
- `src/write_agent/services/`：业务编排层（改写、审核、趋势抓取、工作流作业等）。
- `src/write_agent/models/`：SQLModel 数据模型。
- `src/write_agent/observability/`：可观测中间件、事件发射、编号注册与错误契约。
- `src/write_agent/core/`：配置、数据库、日志基础设施。
- `frontend/src/pages/`：页面级功能模块。
- `frontend/src/services/api.ts`：前端唯一 API 封装与错误处理入口。
- `frontend/src/types/index.ts`：前端类型契约。
- `frontend/src/i18n/messages.ts`：文案与 i18n 词条。
- `tests/`：后端 pytest 回归测试。
- `docs/specs/`：开发规范与验收清单权威文档。
- `docs/CHANGELOG.md`：变更与验证记录。

## 常用命令

| 命令 | 用途 |
|------|------|
| `uv sync` | 安装后端依赖 |
| `cd frontend && npm install` | 安装前端依赖 |
| `cp .env.example .env` | 初始化环境变量 |
| `PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/uvicorn write_agent.main:app --host 127.0.0.1 --port 8000` | 启动后端（README 基线） |
| `cd frontend && npm run dev` | 启动前端开发服务 |
| `PYTHONPATH=src uv run pytest -q` | 后端全量回归 |
| `PYTHONPATH=src uv run pytest -q tests/<module>.py` | 后端定向回归 |
| `cd frontend && npm run build` | 前端构建验收（必跑） |
| `cd frontend && npm run lint` | 前端静态检查 |
| `python scripts/acceptance_smoke.py` | 冒烟验证脚本 |
| `python scripts/create_db.py` | 初始化数据库 |

> 补充：后端 lint/format 统一命令在仓库内未显式定义（**待确认**）。

## 开发规范（Claude Code / Codex）

### 1) 必读顺序（先读再改）

1. `AGENTS.md`
2. `docs/specs/development-spec-v1.md`
3. `docs/specs/verification-checklist.md`
4. `docs/CHANGELOG.md` 最近日期条目

### 2) 默认执行顺序

1. 明确改动影响面（前端/后端/可观测）。
2. 对照 SPEC 确认约束（尤其 observability 与兼容性）。
3. 实施改动（遵循 API → Service → Model 分层）。
4. 按变更分类执行验证命令（见验收清单）。
5. 更新 `docs/CHANGELOG.md`，记录命令与结果。

### 3) 关键硬约束

- 新 API / 关键行为必须接入 observability：`obs_scope(...)`、`emit_obs_event(...)`。
- 新节点/行为必须注册到 `src/write_agent/observability/registry.py`。
- 错误响应必须包含 trace 相关契约字段，且响应头含 `X-Trace-Id` / `X-Request-Id`。
- 前端新增接口字段时，必须同步 `frontend/src/types/index.ts`。
- 前端新增文案必须同步 `frontend/src/i18n/messages.ts`。
- 默认向后兼容：优先新增字段，避免直接删改既有语义。

### 4) 验收门槛（最小集）

- 前端改动：`cd frontend && npm run build`
- 后端业务改动：`PYTHONPATH=src uv run pytest -q <相关测试>`
- 可观测/核心链路改动：`PYTHONPATH=src uv run pytest -q`

## 修改代码时注意事项

### 先读这些文件再下刀

- 后端入口与错误契约：`src/write_agent/main.py`
- 可观测注册表：`src/write_agent/observability/registry.py`
- API 聚合顺序：`src/write_agent/api/__init__.py`
- 前端 API 与错误拼接：`frontend/src/services/api.ts`
- 前端类型定义：`frontend/src/types/index.ts`
- i18n 词条：`frontend/src/i18n/messages.ts`

### 高风险区域（谨慎改动）

- 全局异常处理和响应结构（影响所有 API 与前端错误提示）。
- SSE 事件结构与 `obs` 字段（影响流式页面与排障链路）。
- 定时任务与刷新锁逻辑（GitHub/Linux.do 趋势，易引入并发或冷却问题）。
- 路由注册顺序（例如 `/covers/styles` 与 `/covers/{cover_id}` 的匹配先后）。

### 禁止事项

- 不得在代码中硬编码密钥/token。
- 不得绕开可观测契约直接返回“裸错误”。
- 不得在未完成最小验收前宣称完成。

## 输出风格要求（项目内协作）

- 默认中文沟通，先给结论再给理由。
- 回答聚焦“为什么 + 用户影响”，不要只描述实现细节。
- 改动说明需给出可定位文件路径；涉及行为变更时明确影响范围。
- 不确定信息必须显式标注“待确认”，禁止编造。
- 优先做最小必要改动，避免与当前任务无关的重构。

## 待确认清单

- 生产部署标准流程（是否已有固定环境/脚本）。
- CI 流水线与 PR 必检项的自动化配置位置。
- 前端 E2E 测试基线命令（当前 `frontend/package.json` 未定义 test/e2e script）。
- 后端统一 lint/format/type-check 命令（仓库内未显式声明）。

---

**最后更新**：2026-04-20