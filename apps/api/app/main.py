from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings
from app.db.readiness import database_is_ready

settings = get_settings()

app = FastAPI(title=settings.project_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def readinesscheck() -> dict:
    if not database_is_ready():
        raise HTTPException(status_code=503, detail="Database is not ready.")
    return {"status": "ready"}


app.include_router(router, prefix=settings.api_v1_prefix)
