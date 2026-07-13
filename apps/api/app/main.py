from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.auth import request_id_for
from app.config import get_settings
from app.db.readiness import database_is_ready

settings = get_settings()

# OpenAPI remains convenient for the local demo, but an authenticated deployment
# should not publish its operational surface anonymously.
app = FastAPI(
    title=settings.project_name,
    version="0.1.0",
    docs_url="/docs" if not settings.auth_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if not settings.auth_enabled else None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def safe_request_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    """Do not echo request values such as invite tokens or external IDs."""
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "type": item.get("type", "value_error"),
                    "loc": item.get("loc", ()),
                    "msg": item.get("msg", "Invalid request."),
                }
                for item in error.errors()
            ]
        },
    )


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request_id_for(request)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
def healthcheck() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def readinesscheck() -> dict:
    if not database_is_ready():
        raise HTTPException(status_code=503, detail="Database is not ready.")
    return {"status": "ready"}


app.include_router(router, prefix=settings.api_v1_prefix)
