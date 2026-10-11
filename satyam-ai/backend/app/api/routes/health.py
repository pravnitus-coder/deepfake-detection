from fastapi import APIRouter
from app.core.config import get_settings
from app.models.model_registry import get_audio_detector, get_detector

router = APIRouter()


@router.get("/health")
def health():
    st = get_detector().status()
    audio = get_audio_detector().status()
    settings = get_settings()
    return {"status": "ok", "model": st, "audio_model": audio,
            "upload_simulation_enabled": settings.env != "production" and settings.upload_simulation_enabled,
            "upload_chunk_size_bytes": settings.upload_chunk_size_bytes,
            "upload_max_concurrent_chunks": settings.upload_max_concurrent_chunks,
            "upload_max_retries": settings.upload_max_retries,
            "upload_retry_delays_seconds": settings.upload_retry_delays_seconds,
            "upload_request_timeout_seconds": settings.upload_request_timeout_seconds,
            "modules": {"metadata": "ready", "integrity": "ready (JPEG only)", "video_frames": "sampled frames; image-model adapter",
            "ai_model": "ready" if st["ready"] else "unavailable", "audio_model": "ready" if audio["ready"] else "unavailable",
            "audio_visual": "unavailable (not implemented)"}}
