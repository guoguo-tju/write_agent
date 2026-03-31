# Write Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](../LICENSE)

一个覆盖风格提取、改写、审核、封面生成与公众号排版发布的全栈写作智能体（FastAPI + React/Vite）。

[English](../README.md)

## 亮点与业务价值

- 把原本碎片化的创作动作产品化为标准流程：素材检索、风格约束改写、质量审核、人工复核、封面生成、排版发布形成闭环。
- 在我们的实践中，对个人或团队的收益主要体现在两点：效率上，长文产出可从小时级缩短到十分钟级；质量上，输出风格更稳定、可复审、可回放，不再依赖单次临场 Prompt。
- 写作阶段支持 RAG 检索素材库，并在结果侧展示本次引用素材，便于核查与复用。
- 改写支持受控主编闭环：`首稿 -> 首审 ->（不通过）二次写稿 -> 二审`，后端强制 `max_retries=1`，防止无限循环。
- 公众号排版能力：根据公众号格式做多种风格排版，并一键导出到公众号。

## 主要流程与页面截图

### 端到端流程图

![Write Agent 内容主流程图](./diagrams/write-agent-content-workflow.svg)

1. **改写**：输入原文、选择风格、设置目标长度（预设 `100-8000`，默认 `500`）并流式输出。首页会实时提示闭环阶段（首次写稿、首次主编审核、二次写稿、二次审核、最终状态）。顶部导航支持全站 `CN / EN` 切换，选择会持久化到 `localStorage`（`write_agent_lang`）。

![改写页面](./screenshots/rewrite-page-v2.png)

2. **风格管理**：创建并复用写作风格 DNA。

![风格页面](./screenshots/styles-page-v2.png)

3. **素材库（RAG）**：收集素材、检索测试、写作时引用。

![素材库页面](./screenshots/materials-page-v2.png)

4. **审核**：查看改写结果并支持人工二次编辑。

![审核页面](./screenshots/reviews-page-v2.png)

5. **封面生成**：基于改写结果按多种模式和比例生成封面。

![封面页面](./screenshots/covers-page-v2.png)

6. **排版**：可从改写/审核/封面页一键“去排版”，携带 `rewrite_id` 自动导入正文与封面（若存在），并在 `/layout` 做主题切换、实时预览和公众号复制。

![排版页面](./screenshots/layout-page-v2.png)

7. **GitHub 趋势**：按周抓取过去一周 GitHub Star 新增最多的 Top10 项目，支持周选择与手动刷新。每条项目可一键加入素材库或进入改写，打通“发现选题 -> 沉淀素材 -> 进入创作”。

![GitHub 趋势页面](./screenshots/github-trends-page-v2.png)

8. **Linux.do 趋势**：按 `7天 / 30天` 聚合 Linux.do 公开热帖，支持最近 12 期历史切换、单标签后端筛选，以及带冷却与限流退避的手动刷新。每条帖子可一键“入素材”或“去改写”。

![Linux.do 趋势页面](./screenshots/linuxdo-trends-page-v2.png)

## 快速开始

### 1. 拉代码并安装依赖

```bash
git clone https://github.com/guoguo-tju/write_agent.git
cd write_agent
uv sync
cd frontend && npm install && cd ..
```

### 2. 配置 API Key

```bash
cp .env.example .env
```

编辑 `.env`：

- 必填：`OPENAI_API_KEY`、`VOLCENGINE_API_KEY`
- 可选：`SILICONFLOW_API_KEY`（用于写作阶段的 RAG 向量化检索与引用展示）
- 可选：`GITHUB_TOKEN`（或 `GITHUB_PERSONAL_ACCESS_TOKEN`），用于 GitHub 趋势增强抓取，信息更完整。

### 3. 启动后端

```bash
PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/uvicorn write_agent.main:app --host 127.0.0.1 --port 8000
```

### 4. 启动前端

```bash
cd frontend
npm run dev
```

### 5. 本地访问

- 前端：`http://127.0.0.1:5173`
- 后端文档：`http://127.0.0.1:8000/docs`

建议首次体验路径：`改写 -> 审核 -> 封面 -> 排版(/layout)`，完整走一遍最能感受流程闭环。

说明：若未配置 `SILICONFLOW_API_KEY`，主流程可正常体验，但写作阶段的 RAG 检索与引用展示会受限。

## 项目结构

```text
.
├── src/write_agent/        # 后端（api、models、services）
├── frontend/               # React + Vite 前端
├── scripts/                # 初始化与冒烟脚本
├── tests/                  # 后端测试
├── data/                   # sqlite + chroma 数据
└── docs/screenshots/       # README 截图
```

## 开发规范入口

- AI 迭代入口：[`AGENTS.md`](../AGENTS.md)
- 全栈开发规范：[`docs/specs/development-spec-v1.md`](./specs/development-spec-v1.md)
- 验收清单：[`docs/specs/verification-checklist.md`](./specs/verification-checklist.md)

## 常见问题

### 1）后端启动了，但改写/风格提取/审核失败

检查 `.env` 中 `OPENAI_API_KEY` 以及 OpenAI 兼容配置是否正确。

### 2）封面生成失败

检查 `VOLCENGINE_API_KEY`、`VOLCENGINE_BASE_URL` 与模型配置。

### 3）素材检索结果为空

检查 `SILICONFLOW_API_KEY` 和 embedding 服务网络连通性。

### 4）前端连不上后端（CORS 或网络问题）

建议前端使用 `http://127.0.0.1:5173`，后端使用 `http://127.0.0.1:8000`，并保持 `VITE_API_URL` 一致。

### 5）为什么 GitHub 里看不到封面图片？

封面图片属于运行时本地资产，默认保存在 `./data/covers`，该目录已被 Git 忽略，不会上传到仓库。

### 6）GitHub 趋势提示“未配置 GITHUB_TOKEN，已降级”是什么意思？

表示系统已自动回退到基础抓取流程，不会阻断“入素材/去改写”等主流程；配置 `GITHUB_TOKEN`（或 `GITHUB_PERSONAL_ACCESS_TOKEN`）后可获得更完整的增强信息。

## 许可证

[MIT License](../LICENSE)。
