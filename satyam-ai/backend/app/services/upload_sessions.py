"""Durable, owner-scoped chunk storage and upload-session lifecycle."""
import hashlib
import hmac
import json
import os
import pathlib
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from app.core.config import get_settings
from app.db.database import conn
from app.services.validation import ValidationError

_locks_guard = threading.Lock()
_chunk_locks: dict[tuple[str, int], threading.Lock] = {}
_chunk_slots = threading.BoundedSemaphore(max(1, get_settings().upload_max_concurrent_chunks))
_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_HASH = re.compile(r"^[0-9a-fA-F]{64}$")
_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp"},
    "video": {".mp4", ".mov", ".avi", ".webm"},
    "audio": {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"},
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _root() -> pathlib.Path:
    root = pathlib.Path(get_settings().upload_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _get(upload_id: str, user_id: str) -> dict[str, Any] | None:
    with conn() as database:
        database.row_factory = sqlite3.Row
        row = database.execute("SELECT * FROM uploads WHERE id=? AND user_id=?", (upload_id, user_id)).fetchone()
    return dict(row) if row else None


def _check_live(session: dict[str, Any]) -> None:
    if datetime.fromisoformat(session["expires_at"]) <= _now():
        expire(session["id"])
        raise ValueError("Upload session expired. Start a new upload; previously confirmed chunks were removed.")


def _lock_for(upload_id: str, index: int) -> threading.Lock:
    key = (upload_id, index)
    with _locks_guard:
        if key not in _chunk_locks:
            _chunk_locks[key] = threading.Lock()
        return _chunk_locks[key]


def create(user_id: str, kind: str, filename: str, size: int, checksum: str,
           declared_mime: str, simulation: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    if kind not in _EXTENSIONS:
        raise ValueError("Unsupported media type.")
    safe_name = pathlib.PurePath(filename.replace("\\", "/")).name
    if not safe_name or len(safe_name) > 255 or "\x00" in safe_name:
        raise ValueError("Invalid file name.")
    if pathlib.Path(safe_name).suffix.lower() not in _EXTENSIONS[kind]:
        raise ValueError(f"Unsupported {kind} file extension.")
    limits = {"image": settings.max_image_mb, "video": settings.max_video_mb, "audio": settings.max_audio_mb}
    if not isinstance(size, int) or size <= 0 or size > limits[kind] * 1024 * 1024:
        raise ValueError(f"Invalid file size. The limit for {kind}s is {limits[kind]:g} MB.")
    if not _HASH.fullmatch(checksum):
        raise ValueError("A valid 64-character SHA-256 checksum is required.")
    chunk_size = settings.upload_chunk_size_bytes
    if not 64 * 1024 <= chunk_size <= 8 * 1024 * 1024:
        raise RuntimeError("SATYAM_UPLOAD_CHUNK_SIZE_BYTES must be between 65536 and 8388608.")
    upload_id, now = str(uuid.uuid4()), _now()
    directory = _root() / upload_id
    directory.mkdir(mode=0o700)
    expires = now + timedelta(minutes=settings.upload_session_minutes)
    total = (size + chunk_size - 1) // chunk_size
    try:
        with conn() as database:
            database.execute(
                """INSERT INTO uploads(id,user_id,kind,filename,declared_mime,expected_size,expected_sha256,
                   chunk_size,total_chunks,status,created_at,expires_at,storage_path,simulation_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (upload_id, user_id, kind, safe_name, declared_mime[:128], size, checksum.lower(),
                 chunk_size, total, "uploading", now.isoformat(), expires.isoformat(), str(directory),
                 json.dumps(simulation) if simulation else None),
            )
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return status(upload_id, user_id)


def status(upload_id: str, user_id: str) -> dict[str, Any]:
    session = _get(upload_id, user_id)
    if not session:
        raise KeyError("Upload session not found.")
    _check_live(session)
    with conn() as database:
        rows = database.execute("SELECT chunk_index,size_bytes FROM upload_chunks WHERE upload_id=? ORDER BY chunk_index",
                                (upload_id,)).fetchall()
    received = [int(row[0]) for row in rows]
    confirmed_bytes = sum(int(row[1]) for row in rows)
    received_set = set(received)
    return {
        "upload_id": upload_id, "file_name": session["filename"], "media_type": session["kind"],
        "expected_size": session["expected_size"], "chunk_size": session["chunk_size"],
        "total_chunks": session["total_chunks"], "received_chunks": received,
        "missing_chunks": [index for index in range(session["total_chunks"]) if index not in received_set],
        "confirmed_bytes": confirmed_bytes, "status": session["status"],
        "expires_at": session["expires_at"], "analysis_id": session["analysis_id"],
    }


def store_chunk(upload_id: str, user_id: str, index: int, data: bytes,
                content_range: str | None, chunk_checksum: str | None) -> dict[str, Any]:
    session = _get(upload_id, user_id)
    if not session:
        raise KeyError("Upload session not found.")
    _check_live(session)
    if session["status"] != "uploading":
        raise ValueError(f"Upload is {session['status']} and no longer accepts chunks.")
    if not isinstance(index, int) or not 0 <= index < session["total_chunks"]:
        raise IndexError("Chunk index is outside this upload.")
    start = index * session["chunk_size"]
    expected_bytes = min(session["chunk_size"], session["expected_size"] - start)
    match = _RANGE.fullmatch(content_range or "")
    if not match or tuple(map(int, match.groups())) != (start, start + expected_bytes - 1, session["expected_size"]):
        raise ValueError("Content-Range does not match this chunk's expected byte range.")
    if len(data) != expected_bytes:
        raise ValueError(f"Chunk must contain exactly {expected_bytes} bytes.")
    actual_hash = hashlib.sha256(data).hexdigest()
    if not chunk_checksum or not _HASH.fullmatch(chunk_checksum) or not hmac.compare_digest(actual_hash, chunk_checksum.lower()):
        raise ValueError("Chunk SHA-256 checksum mismatch.")
    lock = _lock_for(upload_id, index)
    with _chunk_slots, lock:
        session = _get(upload_id, user_id)
        if not session:
            raise KeyError("Upload session not found.")
        _check_live(session)
        with conn() as database:
            old = database.execute("SELECT size_bytes,sha256 FROM upload_chunks WHERE upload_id=? AND chunk_index=?",
                                   (upload_id, index)).fetchone()
        if old:
            path = pathlib.Path(session["storage_path"]) / f"{index:08d}.part"
            stored_hash = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
            if old[0] == len(data) and old[1] == actual_hash and hmac.compare_digest(stored_hash, actual_hash):
                return {"upload_id": upload_id, "chunk_index": index, "confirmed": True,
                        "duplicate": True, "size_bytes": len(data), "sha256": actual_hash}
            raise ValueError("A different chunk is already stored at this index.")
        directory = pathlib.Path(session["storage_path"])
        temporary = directory / f".{index:08d}.{uuid.uuid4().hex}.tmp"
        target = directory / f"{index:08d}.part"
        try:
            with temporary.open("xb") as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            with conn() as database:
                database.execute(
                    "INSERT INTO upload_chunks(upload_id,chunk_index,size_bytes,sha256,stored_at) VALUES(?,?,?,?,?)",
                    (upload_id, index, len(data), actual_hash, _now().isoformat()),
                )
        finally:
            if temporary.exists():
                temporary.unlink()
    return {"upload_id": upload_id, "chunk_index": index, "confirmed": True,
            "duplicate": False, "size_bytes": len(data), "sha256": actual_hash}


def assemble(upload_id: str, user_id: str) -> tuple[pathlib.Path, dict[str, Any]]:
    session = _get(upload_id, user_id)
    if not session:
        raise KeyError("Upload session not found.")
    _check_live(session)
    if session["status"] == "complete":
        raise ValueError("Upload is already complete.")
    if session["status"] != "uploading":
        raise ValueError(f"Upload is {session['status']}.")
    current = status(upload_id, user_id)
    if current["missing_chunks"]:
        raise IncompleteError(current)
    with conn() as database:
        changed = database.execute("UPDATE uploads SET status='verifying' WHERE id=? AND user_id=? AND status='uploading'",
                                   (upload_id, user_id)).rowcount
    if changed != 1:
        raise ValueError("Upload completion is already in progress.")
    directory = pathlib.Path(session["storage_path"])
    final_tmp = directory / f".assembled.{uuid.uuid4().hex}.tmp"
    digest, total = hashlib.sha256(), 0
    try:
        with final_tmp.open("xb") as output:
            for index in range(session["total_chunks"]):
                chunk_path = directory / f"{index:08d}.part"
                with chunk_path.open("rb") as part:
                    while block := part.read(1024 * 1024):
                        total += len(block)
                        digest.update(block)
                        output.write(block)
            output.flush()
            os.fsync(output.fileno())
        if total != session["expected_size"]:
            raise ValueError("Assembled file size does not match the declared size.")
        if not hmac.compare_digest(digest.hexdigest(), session["expected_sha256"]):
            raise ValueError("Assembled file SHA-256 does not match the declared checksum.")
        with final_tmp.open("rb") as source:
            head = source.read(32)
        from app.services.validation import validate_upload
        mime = validate_upload(session["kind"], head, total, get_settings(), session["filename"])
        final_path = directory / "verified.media"
        os.replace(final_tmp, final_path)
        return final_path, {**session, "actual_mime": mime, "actual_sha256": digest.hexdigest(),
                            "actual_size": total}
    except Exception:
        with conn() as database:
            database.execute("UPDATE uploads SET status='uploading' WHERE id=? AND user_id=? AND status='verifying'",
                             (upload_id, user_id))
        raise
    finally:
        if final_tmp.exists():
            final_tmp.unlink()


class IncompleteError(ValueError):
    def __init__(self, upload_status: dict[str, Any]):
        super().__init__("Upload is missing one or more required chunks.")
        self.upload_status = upload_status


def mark_complete(upload_id: str, user_id: str, analysis_id: str) -> None:
    with conn() as database:
        changed = database.execute(
            "UPDATE uploads SET status='complete',analysis_id=? WHERE id=? AND user_id=? AND status='verifying'",
            (analysis_id, upload_id, user_id),
        ).rowcount
        if changed != 1:
            raise RuntimeError("Upload session state changed while saving completed analysis.")


def cleanup_completed_files(upload_id: str, user_id: str) -> None:
    session = _get(upload_id, user_id)
    if not session or session["status"] != "complete":
        return
    directory = pathlib.Path(session["storage_path"]).resolve()
    if directory.parent != _root():
        raise RuntimeError("Upload storage path escaped its configured root.")
    if directory.exists():
        shutil.rmtree(directory)


def reset_after_analysis_failure(upload_id: str, user_id: str) -> None:
    with conn() as database:
        database.execute("UPDATE uploads SET status='uploading' WHERE id=? AND user_id=? AND status='verifying'",
                         (upload_id, user_id))


def delete(upload_id: str, user_id: str) -> bool:
    session = _get(upload_id, user_id)
    if not session:
        return False
    directory = pathlib.Path(session["storage_path"]).resolve()
    if directory.parent != _root():
        raise RuntimeError("Upload storage path escaped its configured root.")
    if session["status"] == "verifying":
        raise ValueError("Cannot cancel while the assembled file is being analyzed.")
    with conn() as database:
        database.execute("DELETE FROM uploads WHERE id=? AND user_id=?", (upload_id, user_id))
    if directory.exists():
        shutil.rmtree(directory)
    return True


def expire(upload_id: str) -> None:
    with conn() as database:
        row = database.execute("SELECT storage_path FROM uploads WHERE id=?", (upload_id,)).fetchone()
        if not row:
            return
        database.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
    directory = pathlib.Path(row[0]).resolve()
    if directory.parent == _root() and directory.exists():
        shutil.rmtree(directory)


def cleanup_expired() -> int:
    now = _now().isoformat()
    with conn() as database:
        rows = database.execute("SELECT id FROM uploads WHERE expires_at<=?", (now,)).fetchall()
    for row in rows:
        expire(row[0])
    return len(rows)


def set_simulation(upload_id: str, user_id: str, config: dict[str, Any]) -> None:
    with conn() as database:
        database.execute("UPDATE uploads SET simulation_json=? WHERE id=? AND user_id=?",
                         (json.dumps(config), upload_id, user_id))


def get_simulation(session: dict[str, Any]) -> dict[str, Any] | None:
    value = session.get("simulation_json")
    return json.loads(value) if value else None


def log_simulation(upload_id: str, event: dict[str, Any]) -> None:
    path = _root() / "simulation-events.jsonl"
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps({"timestamp": _now().isoformat(), "upload_id": upload_id, **event}) + "\n")
