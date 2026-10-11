import hashlib
import os
import tempfile
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from PIL import Image
from app.core.config import get_settings
from app.db import database
from app.models.model_registry import get_audio_detector, get_detector
from app.api.routes.auth import require_user
from app.services import metadata_analysis, report_service, validation
from app.services.audio_analysis import analyze_audio
from app.services.evidence_fusion import fuse
from app.services.image_analysis import integrity_module, visual_module
from app.services.video_analysis import VideoAudioError, VideoError, analyze_video, extract_video_audio

router = APIRouter()
_hits = defaultdict(deque)


def rate_limit(request: Request):
    ip, now = (request.client.host if request.client else "?"), time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= get_settings().rate_limit_per_min:
        raise HTTPException(429, "Too many requests. Please wait a minute and try again.")
    q.append(now)


def _read_upload(file: UploadFile, kind: str):
    """Stream to a randomly named temp file, enforcing the size limit; returns (path, sha256, size, mime)."""
    s = get_settings()
    limits = {"image": s.max_image_mb, "video": s.max_video_mb, "audio": s.max_audio_mb}
    limit = int(limits[kind] * 1024 * 1024)
    h, size, head = hashlib.sha256(), 0, b""
    fd, path = tempfile.mkstemp(prefix="satyam_", suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise validation.ValidationError(413, f"File is larger than the {limit // 1048576} MB limit for {kind}s.")
                head = head or chunk[:32]
                h.update(chunk)
                out.write(chunk)
        mime = validation.validate_upload(kind, head, size, s, file.filename)
        return path, h.hexdigest(), size, mime
    except Exception:
        os.unlink(path)
        raise


def _finish(kind, path, sha, size, mime, modules, frames=(), errors=(), media_details=None, audio_segments=(), processing_duration_s=None, user_id=None):
    r = {"id": str(uuid.uuid4()), "created_at": datetime.now(timezone.utc).isoformat(), "kind": kind,
         "file": {"sha256": sha, "size_bytes": size, "mime": mime}, "modules": modules, "fusion": fuse(modules),
         "frames": list(frames), "processing_errors": list(errors),
         "retention": "Original media is deleted right after processing. Results are kept until you delete them."}
    if media_details is not None:
        r["media_details"] = media_details
    if audio_segments:
        r["audio_segments"] = list(audio_segments)
    if processing_duration_s is not None:
        r["processing_duration_s"] = round(processing_duration_s, 3)
    database.save(r, user_id)
    return r


@router.post("/analyze/image")
def analyze_image(file: UploadFile, request: Request, user_id: str = Depends(require_user)):
    rate_limit(request)
    started = time.monotonic()
    path = None
    try:
        path, sha, size, mime = _read_upload(file, "image")
        try:
            with Image.open(path) as probe:
                probe.verify()
            img = Image.open(path)
            img.load()
        except Exception:
            raise validation.ValidationError(422, "The file looks like an image but could not be decoded (malformed or truncated).")
        modules = [metadata_analysis.analyze_metadata(path), integrity_module(img), visual_module(img, get_detector())]
        return _finish("image", path, sha, size, mime, modules,
                       media_details=modules[0].get("details"), processing_duration_s=time.monotonic() - started, user_id=user_id)
    except validation.ValidationError as e:
        raise HTTPException(e.status, e.message)
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


@router.post("/analyze/video")
def analyze_video_route(file: UploadFile, request: Request, user_id: str = Depends(require_user)):
    rate_limit(request)
    started = time.monotonic()
    path = None
    audio_path = None
    try:
        path, sha, size, mime = _read_upload(file, "video")
        settings = get_settings()
        mod, frames, errors, video_details = analyze_video(path, settings, get_detector())
        audio_segments = []
        modules = [mod]
        try:
            audio_bytes = extract_video_audio(path, settings.max_video_seconds)
            if audio_bytes is None:
                modules.append({
                    "id": "video_audio", "name": "Video audio track", "status": "unavailable",
                    "stance": "could_not_check", "method": "FFmpeg audio stream extraction", "version": "1",
                    "observation": None, "score": None, "score_semantics": None, "reliability": "not checked",
                    "summary": "No audio track was found in this video.", "limitations": ["This video has no extractable audio track."],
                })
            else:
                fd, audio_path = tempfile.mkstemp(prefix="satyam_audio_", suffix=".wav")
                with os.fdopen(fd, "wb") as audio_file:
                    audio_file.write(audio_bytes)
                audio_module, audio_segments, audio_details = analyze_audio(audio_path, settings, get_audio_detector())
                audio_module["id"] = "video_audio"
                audio_module["name"] = "Extracted video audio analysis"
                audio_module["details"] = {**audio_module.get("details", {}), **audio_details}
                modules.append(audio_module)
        except VideoAudioError as exc:
            modules.append({
                "id": "video_audio", "name": "Video audio track", "status": "failed",
                "stance": "could_not_check", "method": "FFmpeg audio stream extraction", "version": "1",
                "observation": None, "score": None, "score_semantics": None, "reliability": "not checked",
                "summary": str(exc), "limitations": ["Audio extraction failed; no audio authenticity result is available."],
            })
        except validation.ValidationError as exc:
            modules.append({
                "id": "video_audio", "name": "Extracted video audio analysis", "status": "failed",
                "stance": "could_not_check", "method": "Configured audio model", "version": "n/a",
                "observation": None, "score": None, "score_semantics": None, "reliability": "not checked",
                "summary": exc.message, "limitations": ["The video's visual analysis completed independently; its audio was not successfully analysed."],
            })
        return _finish("video", path, sha, size, mime, modules, frames, errors,
                       media_details=video_details, audio_segments=audio_segments,
                       processing_duration_s=time.monotonic() - started, user_id=user_id)
    except validation.ValidationError as e:
        raise HTTPException(e.status, e.message)
    except VideoError as e:
        raise HTTPException(422, str(e))
    finally:
        if audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)
        if path and os.path.exists(path):
            os.unlink(path)


@router.post("/analyze/audio")
def analyze_audio_route(file: UploadFile, request: Request, user_id: str = Depends(require_user)):
    rate_limit(request)
    started = time.monotonic()
    path = None
    try:
        path, sha, size, mime = _read_upload(file, "audio")
        module, segments, details = analyze_audio(path, get_settings(), get_audio_detector())
        return _finish("audio", path, sha, size, mime, [module], media_details=details,
                       audio_segments=segments, processing_duration_s=time.monotonic() - started, user_id=user_id)
    except validation.ValidationError as e:
        raise HTTPException(e.status, e.message)
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def analyze_verified_path(kind: str, path: str, filename: str, request: Request, user_id: str) -> dict:
    """Pass a verified assembled file through the established analysis entry point."""
    uploaded = StarletteUploadFile(filename=filename, file=open(path, "rb"))
    try:
        if kind == "image":
            return analyze_image(uploaded, request, user_id)
        if kind == "video":
            return analyze_video_route(uploaded, request, user_id)
        if kind == "audio":
            return analyze_audio_route(uploaded, request, user_id)
        raise HTTPException(400, "Unknown media type.")
    finally:
        uploaded.file.close()


@router.get("/analysis/history")
def get_history(limit: int = 20, user_id: str = Depends(require_user)):
    if not 1 <= limit <= 100:
        raise HTTPException(422, "History limit must be between 1 and 100.")
    return database.list_recent(limit, user_id)


@router.get("/analysis/{inv_id}")
def get_analysis(inv_id: str, user_id: str = Depends(require_user)):
    r = database.get(inv_id, user_id)
    if not r:
        raise HTTPException(404, "Investigation not found. It may have been deleted.")
    return r


@router.get("/analysis/{inv_id}/report")
def get_report(inv_id: str, user_id: str = Depends(require_user)):
    r = database.get(inv_id, user_id)
    if not r:
        raise HTTPException(404, "Investigation not found.")
    rep = report_service.build_report(r)
    return JSONResponse(rep, headers={"Content-Disposition": f'attachment; filename="{rep["report_id"]}.json"'})


@router.get("/analysis/{inv_id}/report.pdf")
def get_pdf_report(inv_id: str, user_id: str = Depends(require_user)):
    result = database.get(inv_id, user_id)
    if not result:
        raise HTTPException(404, "Investigation not found.")
    report_id, pdf = report_service.build_pdf_report(result)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'})


@router.delete("/analysis/{inv_id}", status_code=204)
def delete_analysis(inv_id: str, user_id: str = Depends(require_user)):
    if not database.delete(inv_id, user_id):
        raise HTTPException(404, "Investigation not found.")
