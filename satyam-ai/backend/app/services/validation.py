"""Upload validation. Every upload is untrusted: we check magic bytes, not the client's MIME or filename."""
from app.core.config import Settings

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
AUDIO_MIMES = {"audio/wav", "audio/mpeg", "audio/mp4", "audio/aac", "audio/flac", "audio/ogg"}


class ValidationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def sniff(head: bytes):
    """Detect the real type from file signature. Returns a MIME string or None."""
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return "video/x-msvideo"
    if head[:4] == b"fLaC":
        return "audio/flac"
    if head[:4] == b"OggS":
        return "audio/ogg"
    if len(head) > 1 and head[0] == 0xFF and head[1] & 0xF6 == 0xF0:
        return "audio/aac"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "audio/mpeg"
    if head[4:8] == b"ftyp":
        if head[8:12] == b"qt  ":
            return "video/quicktime"
        if head[8:12] in {b"M4A ", b"M4B ", b"M4P "}:
            return "audio/mp4"
        return "video/mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video/webm"
    return None


def validate_upload(kind: str, head: bytes, size: int, s: Settings, filename: str | None = None) -> str:
    if size == 0:
        raise ValidationError(400, "The uploaded file is empty.")
    limits = {"image": s.max_image_mb, "video": s.max_video_mb, "audio": s.max_audio_mb}
    if kind not in limits:
        raise ValidationError(400, "Unknown media type.")
    limit_mb = limits[kind]
    if size > limit_mb * 1024 * 1024:
        raise ValidationError(413, f"File is larger than the {limit_mb:g} MB limit for {kind}s.")
    mime = sniff(head)
    if kind == "audio" and mime == "video/mp4" and filename and filename.lower().endswith(".m4a"):
        mime = "audio/mp4"
    allowed = {"image": IMAGE_MIMES, "video": VIDEO_MIMES, "audio": AUDIO_MIMES}[kind]
    if mime is None or mime not in allowed:
        raise ValidationError(415, f"Unsupported or unrecognised file. Expected a {kind} ({', '.join(sorted(allowed))}).")
    if filename:
        extension = filename.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)
        extension = f".{extension[-1].lower()}" if len(extension) == 2 else ""
        extensions = {
            "image": {".jpg", ".jpeg", ".png", ".webp"},
            "video": {".mp4", ".mov", ".avi", ".webm"},
            "audio": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"},
        }[kind]
        if extension not in extensions:
            raise ValidationError(415, f"Unsupported file extension for {kind}.")
    return mime
