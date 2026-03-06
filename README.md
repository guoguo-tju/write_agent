# Write Agent

A full-stack AI writing agent for style extraction, rewriting, review, and cover generation (FastAPI + React/Vite).

[中文文档](./README.zh-CN.md)

## Core Workflow and Screenshots

1. **Rewrite**: input source text, pick style, stream output.

![Rewrite Page](docs/screenshots/rewrite-page-v2.png)

2. **Style Management**: create and reuse writing style DNA.

![Styles Page](docs/screenshots/styles-page-v2.png)

3. **Materials (RAG)**: collect materials, test retrieval, and reuse in writing.

![Materials Page](docs/screenshots/materials-page-v2.png)

4. **Review**: inspect rewrite results and do manual edits when needed.

![Reviews Page](docs/screenshots/reviews-page-v2.png)

5. **Cover Generation**: generate covers from rewrite results with multiple modes and ratios.

![Covers Page](docs/screenshots/covers-page-v2.png)

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/guoguo-tju/write_agent.git
cd write_agent
uv sync
cd frontend && npm install && cd ..
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` with:

- Required: `OPENAI_API_KEY`, `VOLCENGINE_API_KEY`
- Optional: `SILICONFLOW_API_KEY` (for RAG embedding/retrieval)

### 3. Start backend

```bash
PYTHONPATH=src DATABASE_URL=sqlite:///./data/acceptance_write_agent.db .venv/bin/uvicorn write_agent.main:app --host 127.0.0.1 --port 8000
```

### 4. Start frontend

```bash
cd frontend
npm run dev
```

### 5. Open locally

- Frontend: `http://127.0.0.1:5173`
- Backend docs: `http://127.0.0.1:8000/docs`

Note: if `SILICONFLOW_API_KEY` is not set, RAG-related features may be limited, but the main flow still works.

## Project Structure

```text
.
├── src/write_agent/        # backend (api, models, services)
├── frontend/               # React + Vite frontend
├── scripts/                # db/init/smoke scripts
├── tests/                  # backend tests
├── data/                   # sqlite + chroma data
└── docs/screenshots/       # README screenshots
```

## FAQ

### 1) Backend starts but rewrite/style/review fails

Check `OPENAI_API_KEY` and related OpenAI-compatible config in `.env`.

### 2) Cover generation fails

Check `VOLCENGINE_API_KEY`, `VOLCENGINE_BASE_URL`, and model config.

### 3) Materials retrieval is empty

Check `SILICONFLOW_API_KEY` and network access to embedding service.

### 4) Frontend cannot call backend (CORS or network)

Use `http://127.0.0.1:5173` for frontend and `http://127.0.0.1:8000` for backend, and keep `VITE_API_URL` aligned.

## License

MIT License.
