import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import analyze, auth, health, uploads
from app.core.config import get_settings
from app.db.database import init_db

log = logging.getLogger("satyam")
s = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from app.services.upload_sessions import cleanup_expired
    from app.services.auth import cleanup_expired_sessions
    cleanup_expired()
    cleanup_expired_sessions()
    yield


app = FastAPI(
    title="SATYAM AI",
    version="0.1.0",
    docs_url="/api/docs" if s.env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error")
    return JSONResponse(
        {"detail": "Something went wrong while processing this file. Please try again." + (f" ({exc!r})" if s.env != "production" else "")},
        status_code=500,
    )
