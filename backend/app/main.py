from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    analyses,
    api_settings,
    chat,
    competitors,
    health,
    knowledge,
    observability,
    qa,
    reports,
    revisions,
    runs,
    sources,
    timeline,
)
from app.core.config import get_settings
from app.db.session import init_db

settings = get_settings()

app = FastAPI(title="Competitive Agent System API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


app.include_router(health.router, prefix="/api")
app.include_router(api_settings.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(competitors.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(analyses.router, prefix="/api")
app.include_router(timeline.router, prefix="/api")
app.include_router(sources.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(qa.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(revisions.router, prefix="/api")
app.include_router(observability.router, prefix="/api")
