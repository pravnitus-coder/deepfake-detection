import asyncio
import time
from collections import defaultdict, deque
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from app.api.routes.auth import require_user
from app.api.routes import analyze
from app.core.config import get_settings
from app.db import database
from app.services import upload_sessions

router = APIRouter()
_hits: dict[str, deque[float]] = defaultdict(deque)


class Simulation(BaseModel):
    fault: str = Field(pattern="^(disconnect|timeout|http_503|retry_exhaust)$")
    threshold_percent: int = Field(default=50, ge=25, le=75)
    recovery_seconds: int = Field(default=8, ge=1, le=180)


class InitiateRequest(BaseModel):
    media_type: str
    file_name: str = Field(min_length=1, max_length=255)
    file_size: int = Field(gt=0)
    file_sha256: str = Field(pattern="^[0-9a-fA-F]{64}$")
    mime_type: str = Field(default="application/octet-stream", max_length=128)
    simulation: Simulation | None = None


def _rate_limit(user_id: str) -> None:
    now = time.monotonic()
    hits = _hits[user_id]
    while hits and now - hits[0] >= 60:
        hits.popleft()
    if len(hits) >= 240:
        raise HTTPException(429, "Too many upload requests. Wait a minute and resume.")
    hits.append(now)


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(404, str(exc).strip("'"))
    if isinstance(exc, IndexError):
        return HTTPException(416, str(exc))
    if isinstance(exc, upload_sessions.IncompleteError):
        return HTTPException(409, {"message": str(exc), "status": exc.upload_status})
    if isinstance(exc, (ValueError, upload_sessions.ValidationError)):
        return HTTPException(422, str(exc))
    raise exc


@router.post("/uploads/initiate", status_code=201)
def initiate(body: InitiateRequest, request: Request, user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    simulation: dict[str, Any] | None = None
    if body.simulation:
        settings = get_settings()
        if settings.env == "production" or not settings.upload_simulation_enabled:
            raise HTTPException(403, "Upload failure simulation is disabled.")
        simulation = {**body.simulation.model_dump(), "triggered": False, "recover_at": None, "events": []}
    try:
        return upload_sessions.create(user_id, body.media_type.lower(), body.file_name, body.file_size,
                                      body.file_sha256, body.mime_type, simulation)
    except Exception as exc:
        if isinstance(exc, (ValueError, RuntimeError)):
            raise HTTPException(422, str(exc)) from exc
        raise


async def _read_chunk(request: Request, max_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, "Chunk exceeds the configured chunk-size limit.")
        except ValueError as exc:
            raise HTTPException(400, "Invalid Content-Length header.") from exc
    chunks: list[bytes] = []
    total = 0
    async for part in request.stream():
        total += len(part)
        if total > max_bytes:
            raise HTTPException(413, "Chunk exceeds the configured chunk-size limit.")
        chunks.append(part)
    return b"".join(chunks)


async def _inject_simulated_fault(upload_id: str, user_id: str, index: int) -> None:
    session = upload_sessions._get(upload_id, user_id)
    if not session:
        return
    simulation = upload_sessions.get_simulation(session)
    if not simulation:
        return
    now = time.time()
    if simulation.get("triggered"):
        recovery = simulation.get("recover_at")
        if recovery and now < recovery:
            upload_sessions.log_simulation(upload_id, {"event": "fault_injected", "fault": simulation["fault"],
                                                       "chunk_index": index})
            if simulation["fault"] == "timeout":
                await asyncio.sleep(min(5, max(1, recovery - now)))
                raise HTTPException(408, "Development simulation: request timed out; retry after recovery.")
            raise HTTPException(503, "Development simulation: temporary upload interruption.",
                                headers={"Retry-After": str(max(1, int(recovery - now)))})
        upload_sessions.log_simulation(upload_id, {"event": "recovered", "fault": simulation["fault"],
                                                   "chunk_index": index})
        simulation["triggered"] = False
        simulation["recover_at"] = None
        simulation["finished"] = True
        upload_sessions.set_simulation(upload_id, user_id, simulation)
        return
    if simulation.get("finished"):
        return
    current = upload_sessions.status(upload_id, user_id)
    threshold = session["expected_size"] * simulation["threshold_percent"] / 100
    if current["confirmed_bytes"] < threshold:
        return
    duration = max(simulation["recovery_seconds"], 60 if simulation["fault"] == "retry_exhaust" else 1)
    simulation["triggered"] = True
    simulation["recover_at"] = now + duration
    simulation["events"].append({"event": "interrupted", "chunk_index": index, "confirmed_bytes": current["confirmed_bytes"]})
    upload_sessions.set_simulation(upload_id, user_id, simulation)
    upload_sessions.log_simulation(upload_id, {"event": "interrupted", "fault": simulation["fault"],
                                               "threshold_percent": simulation["threshold_percent"],
                                               "confirmed_bytes": current["confirmed_bytes"], "chunk_index": index})
    if simulation["fault"] == "timeout":
        await asyncio.sleep(min(5, duration))
        raise HTTPException(408, "Development simulation: request timed out; retry after recovery.")
    raise HTTPException(503, "Development simulation: temporary upload interruption.",
                        headers={"Retry-After": str(duration)})


@router.put("/uploads/{upload_id}/chunks/{chunk_index}")
async def put_chunk(upload_id: str, chunk_index: int, request: Request,
                    user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    try:
        status = upload_sessions.status(upload_id, user_id)
        if not 0 <= chunk_index < status["total_chunks"]:
            raise IndexError("Chunk index is outside this upload.")
        await _inject_simulated_fault(upload_id, user_id, chunk_index)
        data = await _read_chunk(request, status["chunk_size"])
        return upload_sessions.store_chunk(upload_id, user_id, chunk_index, data,
                                           request.headers.get("content-range"),
                                           request.headers.get("x-chunk-sha256"))
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.get("/uploads/{upload_id}/status")
def get_status(upload_id: str, user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    try:
        return upload_sessions.status(upload_id, user_id)
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/uploads/{upload_id}/resume")
def resume(upload_id: str, user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    try:
        result = upload_sessions.status(upload_id, user_id)
        if result["status"] not in {"uploading", "complete"}:
            raise HTTPException(409, f"Upload cannot resume while it is {result['status']}.")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.post("/uploads/{upload_id}/complete")
def complete(upload_id: str, request: Request, user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    try:
        current = upload_sessions.status(upload_id, user_id)
        if current["status"] == "complete" and current["analysis_id"]:
            result = database.get(current["analysis_id"], user_id)
            if result:
                return {"upload": current, "investigation": result}
            raise HTTPException(409, "The stored analysis result is missing; contact the administrator.")
        path, verified = upload_sessions.assemble(upload_id, user_id)
        try:
            investigation = analyze.analyze_verified_path(
                verified["kind"], str(path), verified["filename"], request, user_id,
            )
        except Exception:
            upload_sessions.reset_after_analysis_failure(upload_id, user_id)
            raise
        upload_sessions.mark_complete(upload_id, user_id, investigation["id"])
        upload_sessions.cleanup_completed_files(upload_id, user_id)
        return {"upload": upload_sessions.status(upload_id, user_id), "investigation": investigation}
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc


@router.delete("/uploads/{upload_id}", status_code=204)
def cancel(upload_id: str, user_id: str = Depends(require_user)):
    _rate_limit(user_id)
    try:
        if not upload_sessions.delete(upload_id, user_id):
            raise HTTPException(404, "Upload session not found.")
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate(exc) from exc
