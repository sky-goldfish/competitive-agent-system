# Competitive Agent System

竞品分析 Agent 协作系统 MVP。

## 文档

- [产品需求文档](docs/prd.md)
- [架构说明](docs/architecture.md)

## 技术栈

- Backend: FastAPI + SQLite + SQLAlchemy + LangGraph
- Frontend: React + Vite + TypeScript
- MVP Provider: Mock LLM + Mock Search

## 启动后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8000
```

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问： http://localhost:5173

API： http://localhost:8000/api/health
