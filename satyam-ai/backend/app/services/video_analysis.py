"""Sampled-frame video investigation. Only sampled frames are examined: this is NOT full temporal analysis."""
import time
import shutil
import subprocess
import cv2
from PIL import Image
from app.core.config import Settings
from app.services.image_analysis import visual_module


class VideoError(Exception):
    pass


class VideoAudioError(Exception):
    pass


def extract_video_audio(path: str, max_seconds: float):
    try:
        import imageio_ffmpeg
        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VideoAudioError("FFmpeg is unavailable, so the video's audio track could not be extracted.")
    try:
        result = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", path, "-map", "0:a:0", "-vn",
             "-t", str(max_seconds + 1), "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise VideoAudioError("Extracting the video's audio exceeded the 45-second time limit.") from exc
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").lower()
        if "matches no streams" in message or "does not contain any stream" in message:
            return None
        raise VideoAudioError("The video's audio track could not be decoded.")
    if not result.stdout:
        return None
    return result.stdout


def analyze_video(path: str, s: Settings, detector):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise VideoError("The video could not be opened. It may be corrupt or use an unsupported codec.")
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or count <= 0:
            raise VideoError("The video has no readable duration, so frames cannot be sampled safely.")
        duration = count / fps
        if duration > s.max_video_seconds:
            raise VideoError(f"Video is {duration:.0f}s long; the limit is {s.max_video_seconds:g}s.")
        times = [i * s.frame_interval_s for i in range(s.max_frames) if i * s.frame_interval_s < duration] or [0.0]
        start, frames, errors = time.monotonic(), [], []
        for i, t in enumerate(times):
            if time.monotonic() - start > s.max_processing_s:
                errors.append(f"Processing time limit reached after {i} frames; remaining frames were skipped.")
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, bgr = cap.read()
            if not ok:
                frames.append({"index": i, "time_s": t, "status": "failed", "stance": "could_not_check",
                               "observation": "Frame could not be decoded."})
                continue
            scale = 1024 / max(bgr.shape[:2])
            if scale < 1:
                bgr = cv2.resize(bgr, None, fx=scale, fy=scale)
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            f = {"index": i, "time_s": round(t, 2), "status": "completed", "brightness": round(float(gray.mean()), 1),
                 "sharpness": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 1)}
            mod = visual_module(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), detector)
            f.update(stance=mod["stance"] if mod["status"] == "completed" else "could_not_check",
                     observation=mod["observation"] or mod["summary"], model_scores=mod["score"], model_status=mod["status"])
            frames.append(f)
    finally:
        cap.release()

    done = [f for f in frames if f.get("model_status") == "completed"]
    flagged = [f for f in done if f["stance"] == "supports_manipulation"]
    meta = {"duration_s": round(duration, 2), "fps": round(fps, 2), "width": w, "height": h, "frame_count": int(count),
            "frames_sampled": len(frames), "sample_interval_s": s.frame_interval_s}
    lim = [f"Only {len(frames)} sampled frame(s) were analysed; this is not a full-video or temporal analysis.",
           "Frame-level model results can disagree; all are listed in the timeline.",
           "Audio-visual consistency is not checked."]
    base = dict(id="video_frames", name="Video frame analysis", method="Sampled-frame image model", version="1",
                score=None, score_semantics=None, reliability="unvalidated", limitations=lim, details=meta)
    if not done:
        mod = dict(base, status="unavailable", stance="could_not_check", observation=None,
                   summary="Frames were extracted but no model verdict is available, so only brightness and sharpness were recorded.")
    else:
        share = len(flagged) / len(done)
        stance = "supports_manipulation" if share >= 0.5 else "supports_authenticity" if not flagged else "inconclusive"
        mod = dict(base, status="completed", stance=stance, observation=f"{len(flagged)} of {len(done)} analysed frames flagged by the model.",
                   score={"flagged_frames": len(flagged), "analysed_frames": len(done)},
                   score_semantics="Counts of frames the model flagged. Not a probability.",
                   summary="Frame results are mixed; inspect the timeline." if stance == "inconclusive" else
                   "Most sampled frames were flagged." if stance == "supports_manipulation" else "No sampled frame was flagged (weak evidence only).")
    return mod, frames, errors, meta
