"""Runtime settings, read from environment variables on each call (easy to override in tests)."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _f(name, default):
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    env: str
    cors_origins: list
    max_image_mb: float
    max_video_mb: float
    max_audio_mb: float
    max_video_seconds: float
    max_audio_seconds: float
    frame_interval_s: float
    max_frames: int
    audio_segment_seconds: float
    max_processing_s: float
    rate_limit_per_min: int
    db_path: str
    hf_model: str
    hf_model_revision: str
    hf_fake_labels: list
    audio_model: str
    audio_model_revision: str
    audio_fake_labels: list
    audio_real_labels: list
    upload_dir: str
    upload_chunk_size_bytes: int
    upload_session_minutes: int
    upload_max_concurrent_chunks: int
    upload_max_retries: int
    upload_retry_base_seconds: float
    upload_retry_delays_seconds: list[float]
    upload_request_timeout_seconds: int
    upload_simulation_enabled: bool


def get_settings() -> Settings:
    return Settings(
        env=os.getenv("SATYAM_ENV", "development"),
        cors_origins=[o.strip() for o in os.getenv("SATYAM_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        max_image_mb=_f("SATYAM_MAX_IMAGE_MB", 10),
        max_video_mb=_f("SATYAM_MAX_VIDEO_MB", 50),
        max_audio_mb=_f("SATYAM_MAX_AUDIO_MB", 30),
        max_video_seconds=_f("SATYAM_MAX_VIDEO_SECONDS", 60),
        max_audio_seconds=_f("SATYAM_MAX_AUDIO_SECONDS", 180),
        frame_interval_s=_f("SATYAM_FRAME_INTERVAL_S", 2),
        max_frames=int(_f("SATYAM_MAX_FRAMES", 12)),
        audio_segment_seconds=_f("SATYAM_AUDIO_SEGMENT_SECONDS", 10),
        max_processing_s=_f("SATYAM_MAX_PROCESSING_S", 90),
        rate_limit_per_min=int(_f("SATYAM_RATE_LIMIT_PER_MIN", 20)),
        db_path=os.getenv("SATYAM_DB_PATH", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "satyam.db"))),
        hf_model=os.getenv("SATYAM_HF_MODEL", "").strip(),
        hf_model_revision=os.getenv("SATYAM_HF_MODEL_REVISION", "").strip(),
        hf_fake_labels=[l.strip().lower() for l in os.getenv("SATYAM_HF_FAKE_LABELS", "artificial,fake,ai,ai-generated,generated").split(",") if l.strip()],
        audio_model=os.getenv("SATYAM_AUDIO_MODEL", "").strip(),
        audio_model_revision=os.getenv("SATYAM_AUDIO_MODEL_REVISION", "").strip(),
        audio_fake_labels=[l.strip().lower() for l in os.getenv("SATYAM_AUDIO_FAKE_LABELS", "fake,spoof,synthetic,ai-generated,artificial").split(",") if l.strip()],
        audio_real_labels=[l.strip().lower() for l in os.getenv("SATYAM_AUDIO_REAL_LABELS", "real,bonafide,genuine").split(",") if l.strip()],
        upload_dir=os.getenv("SATYAM_UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "..", "..", ".satyam_uploads")),
        upload_chunk_size_bytes=int(_f("SATYAM_UPLOAD_CHUNK_SIZE_BYTES", 1024 * 1024)),
        upload_session_minutes=int(_f("SATYAM_UPLOAD_SESSION_MINUTES", 30)),
        upload_max_concurrent_chunks=int(_f("SATYAM_UPLOAD_MAX_CONCURRENT_CHUNKS", 2)),
        upload_max_retries=int(_f("SATYAM_UPLOAD_MAX_RETRIES", 5)),
        upload_retry_base_seconds=_f("SATYAM_UPLOAD_RETRY_BASE_SECONDS", 1),
        upload_retry_delays_seconds=[float(value) for value in os.getenv("SATYAM_UPLOAD_RETRY_DELAYS_SECONDS", "1,2,4,8,16").split(",") if value.strip()],
        upload_request_timeout_seconds=int(_f("SATYAM_UPLOAD_REQUEST_TIMEOUT_SECONDS", 30)),
        upload_simulation_enabled=os.getenv("SATYAM_UPLOAD_SIMULATION_ENABLED", "false").strip().lower() == "true",
    )
