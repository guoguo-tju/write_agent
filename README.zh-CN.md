# Write Agent

一个覆盖风格提取、改写、审核、封面生成的全栈写作智能体（FastAPI + React/Vite）。

[English](./README.md)

## 亮点与业务价值

- 把原本碎片化的创作动作产品化为标准流程：素材检索、风格约束改写、质量审核、人工复核、封面生成形成闭环。
- 在我们的实践中，对个人或团队的收益主要体现在两点：效率上，长文产出可从小时级缩短到十分钟级；质量上，输出风格更稳定、可复审、可回放，不再依赖单次临场 Prompt。
- 写作阶段支持 RAG 检索素材库，并在结果侧展示本次引用素材，便于核查与复用。

## 主要流程与页面截图

1. **改写**：输入原文、选择风格、流式输出结果。

![改写页面](docs/screenshots/rewrite-page-v2.png)

2. **风格管理**：创建并复用写作风格 DNA。

![风格页面](docs/screenshots/styles-page-v2.png)

3. **素材库（RAG）**：收集素材、检索测试、写作时引用。

![素材库页面](docs/screenshots/materials-page-v2.png)

4. **审核**：查看改写结果并支持人工二次编辑。

![审核页面](docs/screenshots/reviews-page-v2.png)

5. **封面生成**：基于改写结果按多种模式和比例生成封面。

![封面页面](docs/screenshots/covers-page-v2.png)

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

## 许可证

MIT License。
