# Write Agent

基于 FastAPI、LangChain、LangGraph、RAG 和 OpenAI 兼容接口构建的写作智能体，覆盖风格提取、改写、审核和封面生成全流程。

[English](./README.md)

## 目录

- [功能特性](#功能特性)
- [界面截图](#界面截图)
- [技术栈与架构](#技术栈与架构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [运行与验证](#运行与验证)
- [使用流程](#使用流程)
- [项目结构](#项目结构)
- [安全说明（开源前必看）](#安全说明开源前必看)
- [常见问题](#常见问题)
- [贡献指南](#贡献指南)
- [许可证](#许可证)

## 功能特性

- 支持从多篇参考文章提取写作风格。
- 风格提取支持 SSE 实时进度（`start/progress/content/done/error`）。
- 素材库管理（新增/查询/删除），支持来源 URL 与标签。
- 改写支持 SSE 流式输出，可实时查看增量内容与目标字数控制。
- 审核支持流式返回与评分结果。
- 封面生成支持 3 种模式：
  - 自动生成 Prompt
  - 基于封面风格模板
  - 自定义 Prompt
- 封面比例支持：
  - `2.35:1`（公众号封面）
  - `1:1`
  - `9:16`
  - `3:4`
- 支持封面风格管理（创建/查询/删除）。
- 提供改写、审核、封面历史，便于追踪与验收。

## 界面截图

### 1）写作风格提取

![写作风格页面](docs/screenshots/styles-page.png)

### 2）素材库管理

![素材库页面](docs/screenshots/materials-page.png)

### 3）文章改写

![改写页面](docs/screenshots/rewrite-page.png)

### 4）审核流程

![审核页面](docs/screenshots/reviews-page.png)

### 5）封面生成

![封面生成页面](docs/screenshots/covers-page.png)

## 技术栈与架构

- 后端：FastAPI + SQLModel + SQLite
- 工作流/模型编排：LangChain + LangGraph
- 改写/审核模型：兼容 OpenAI 协议的模型服务
- RAG 向量化：SiliconFlow Embedding + Chroma
- 封面生图：火山引擎（Volcengine）API
- 前端：React + TypeScript + Vite

高层流程：

```text
风格提取 -> 素材库（RAG）-> 改写（SSE）-> 审核（SSE）-> 封面（SSE）
```

## 环境要求

- Python `3.10+`（当前项目使用 `3.10`）
- Node.js `18+`
- npm
- uv（[Astral uv](https://docs.astral.sh/uv/)）

## 快速开始

本 README 仅覆盖本地开发部署。

### 1. 拉取代码

```bash
git clone https://github.com/guoguo-tju/write_agent.git
cd write_agent
```

### 2. 后端安装与启动

安装依赖：

```bash
uv sync
```

先基于模板创建 `.env`：

```bash
cp .env.example .env
```

然后编辑 `.env`，填入你自己的 API Key（必填）：
- `OPENAI_API_KEY`
- `VOLCENGINE_API_KEY`

可选（仅在使用 RAG 素材检索时需要）：
- `SILICONFLOW_API_KEY`

创建数据库表：

```bash
PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/python scripts/create_db.py
```

启动后端：

```bash
PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/uvicorn write_agent.main:app --host 127.0.0.1 --port 8000
```

### 3. 前端安装与启动

```bash
cd frontend
npm install
```

可选：指定前端请求后端地址：

```bash
echo "VITE_API_URL=http://127.0.0.1:8000" > .env.local
```

启动前端：

```bash
npm run dev
```

访问地址：

- 前端：`http://127.0.0.1:5173`
- 后端文档：`http://127.0.0.1:8000/docs`

## 环境变量

### 核心功能必填

- 建议先复制 `.env.example` 为 `.env`，再填写密钥。
- `OPENAI_API_KEY`：风格提取、改写、审核依赖。
- `VOLCENGINE_API_KEY`：封面生图依赖。
- `SILICONFLOW_API_KEY`（可选）：仅素材向量化与 RAG 检索依赖。

### 常用可选覆盖项

- `DATABASE_URL`（默认 `sqlite:///./data/acceptance_write_agent.db`）
- `API_HOST`（默认 `0.0.0.0`）
- `API_PORT`（默认 `8000`）
- `DEBUG`（默认 `true`）
- `LOG_LEVEL`（默认 `INFO`）
- 各 Provider 的 Base URL 与模型名（代码中有默认值）。
- 兼容说明：历史 `MINIMAX_*` 环境变量仍可用。

## 运行与验证

### 健康检查

```bash
curl -sS http://127.0.0.1:8000/
curl -sS http://127.0.0.1:8000/health
```

### 验收冒烟测试

```bash
DATABASE_URL=sqlite:///./data/acceptance_write_agent.db PYTHONPATH=src .venv/bin/python scripts/acceptance_smoke.py
```

可选（包含外部 API 校验）：

```bash
DATABASE_URL=sqlite:///./data/acceptance_write_agent.db PYTHONPATH=src .venv/bin/python scripts/acceptance_smoke.py --with-external
```

### 前端构建验证

```bash
cd frontend
npm run build
```

### 后端测试

```bash
PYTHONPATH=src .venv/bin/pytest
```

## 使用流程

部署完成后，按以下流程做端到端验证：

1. 进入 `Styles` 页面，用多篇参考文章创建写作风格。
2. （可选）进入 `Materials` 页面，补充 RAG 素材。
3. 进入 `Home` 页面：
   - 输入原文
   - 选择风格
   - 设置目标字数
   - 发起改写并观察 SSE 流式输出
4. 进入 `Reviews` 页面，查看审核结果与详情。
5. 进入 `Covers` 页面：
   - 选择改写记录
   - 选择生成模式（自动/风格/自定义）
   - 选择比例（`2.35:1`、`1:1`、`9:16`、`3:4`）
   - 生成封面
6. 在封面历史中验证图片与下载链接。

API 细节请在服务启动后查看 FastAPI OpenAPI 文档：
- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/redoc`

## 项目结构

```text
.
├── src/write_agent/
│   ├── api/              # FastAPI 路由层
│   ├── core/             # 配置、日志、数据库引擎
│   ├── models/           # SQLModel 数据模型
│   └── services/         # 业务逻辑（LLM、RAG、改写、审核、封面）
├── frontend/             # React + Vite 前端
├── scripts/              # 数据库初始化、冒烟测试脚本
├── tests/                # 后端测试
├── data/                 # SQLite 与 Chroma 持久化目录
└── docs/                 # 验收与规划文档
```

## 安全说明（开源前必看）

- 不要把真实 API Key 提交到公开仓库。
- 开源前请轮换所有曾在本地 `.env` 中使用过的密钥。
- 密钥只保存在本地 `.env` 或 CI Secret 管理器中。
- 建议开源前补充 `.gitignore`：

```gitignore
.env
.env.*
data/*.db
data/chroma/
```

## 常见问题

### 后端启动正常，但风格提取/改写/审核失败

优先检查 `.env` 中的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`。

### 素材创建成功，但向量检索为空或失败

检查 `SILICONFLOW_API_KEY`、网络连通性和 `./data/chroma` 写权限。

### 封面生成失败

检查 `VOLCENGINE_API_KEY`、模型名和 Base URL 配置。

### 报错缺少数据表或 SQL 异常

执行：

```bash
PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/python scripts/create_db.py
```

### 浏览器出现 CORS 问题

建议前端使用 `http://127.0.0.1:5173`，后端使用 `http://127.0.0.1:8000`，并设置 `VITE_API_URL`。

## 贡献指南

1. Fork 仓库。
2. 新建功能分支。
3. 提交清晰的 Commit 信息。
4. 提交前本地执行：
   - 后端测试（`pytest`）
   - 前端构建（`npm run build`）
   - 冒烟测试（`scripts/acceptance_smoke.py`）
5. 提交 PR，附上：
   - 改动说明
   - 测试结果
   - UI 变更截图（如涉及前端）

## 许可证

本项目采用 MIT License。
