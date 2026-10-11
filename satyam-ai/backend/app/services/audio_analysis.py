"""Bounded audio decoding and optional model inference. No acoustic verdict is invented."""
import math
import shutil
import subprocess
import time
from io import BytesIO

import numpy as np
import soundfile as sf
from app.core.config import Settings
from app.services.validation import ValidationError


def _decode(path: str, max_seconds: float):
    try:
        info = sf.info(path)
        source = path
        decoder = "libsndfile"
    except (RuntimeError, OSError, sf.LibsndfileError):
        source, info = _ffmpeg_decode(path, max_seconds)
        decoder = "FFmpeg"

    if info.frames <= 0 or info.samplerate <= 0 or info.channels <= 0:
        raise ValidationError(422, "The audio file has no readable samples.")
    duration = info.frames / info.samplerate
    if duration > max_seconds:
        raise ValidationError(413, f"Audio is longer than the {max_seconds:g}s limit.")
    if info.channels > 8 or info.samplerate > 192000:
        raise ValidationError(422, "The audio format exceeds the supported channel or sample-rate limit.")
    try:
        samples, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    except (RuntimeError, OSError, sf.LibsndfileError) as exc:
        if decoder != "FFmpeg":
            source, info = _ffmpeg_decode(path, max_seconds)
            try:
                samples, sample_rate = sf.read(source, dtype="float32", always_2d=True)
                if info.frames / info.samplerate > max_seconds:
                    raise ValidationError(413, f"Audio is longer than the {max_seconds:g}s limit.")
                if not samples.size or not np.isfinite(samples).all():
                    raise ValidationError(422, "The audio file contains no usable finite audio samples.")
                return samples, sample_rate, info.channels, "FFmpeg"
            except (RuntimeError, OSError, sf.LibsndfileError) as fallback_exc:
                raise ValidationError(422, "The audio file could not be decoded completely.") from fallback_exc
        raise ValidationError(422, "The audio file could not be decoded completely.") from exc
    return samples, sample_rate, info.channels, decoder


def _ffmpeg_decode(path: str, max_seconds: float):
    try:
        import imageio_ffmpeg
        ffmpeg = shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, OSError, RuntimeError):
        ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValidationError(422, "This audio codec needs FFmpeg. Install the optional audio dependencies or use WAV, FLAC or OGG.")
    try:
        converted = subprocess.run(
            [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", path, "-map", "0:a:0", "-t",
             str(max_seconds + 1), "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
            capture_output=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValidationError(422, "Audio decoding exceeded the 45-second time limit.") from exc
    if converted.returncode != 0 or not converted.stdout:
        raise ValidationError(422, "The audio file could not be decoded. It may be corrupt or contain no audio track.")
    source = BytesIO(converted.stdout)
    try:
        info = sf.info(source)
    except (RuntimeError, OSError, sf.LibsndfileError) as exc:
        raise ValidationError(422, "The audio codec was detected but the decoded samples could not be read.") from exc
    source.seek(0)
    return source, info


def analyze_audio(path: str, s: Settings, detector):
    samples, sample_rate, channels, decoder = _decode(path, s.max_audio_seconds)
    if not samples.size or not np.isfinite(samples).all():
        raise ValidationError(422, "The audio file contains no usable finite audio samples.")
    mono = samples.mean(axis=1)
    duration = len(mono) / sample_rate
    if duration <= 0:
        raise ValidationError(422, "The audio file has no readable duration.")

    status = detector.status()
    base = {
        "id": "audio_model",
        "name": "Synthetic audio classifier",
        "method": status["name"],
        "version": status["version"],
        "score": None,
        "score_semantics": None,
        "reliability": "unvalidated",
        "details": {"duration_s": round(duration, 3), "sample_rate": sample_rate, "channels": channels, "decoder": decoder},
        "limitations": [
            "No transcription, voice identity, or voice-cloning claim is made by this generic audio-classification adapter.",
            "Model scores are raw and uncalibrated; performance depends on the selected model, codec, language and recording conditions.",
            "This project has not validated a configured audio model on a representative test set.",
        ],
    }
    if not status["ready"]:
        return {
            **base,
            "status": "unavailable",
            "stance": "could_not_check",
            "observation": None,
            "summary": f"Audio decoded ({duration:.1f}s), but no authenticity model ran. {status['reason']}",
        }, [], {"duration_s": round(duration, 3), "sample_rate": sample_rate, "channels": channels, "decoder": decoder}

    segment_frames = max(1, int(s.audio_segment_seconds * sample_rate))
    segment_count = math.ceil(len(mono) / segment_frames)
    labels = set()
    segment_results = []
    weighted_scores = {}
    weighted_total = 0
    started = time.monotonic()

    for index in range(segment_count):
        if time.monotonic() - started > s.max_processing_s:
            if not segment_results:
                return {
                    **base,
                    "status": "failed",
                    "stance": "could_not_check",
                    "observation": None,
                    "summary": "Audio inference exceeded the processing time limit before a segment completed.",
                }, [], {"duration_s": round(duration, 3), "sample_rate": sample_rate, "channels": channels, "decoder": decoder}

            break
        start = index * segment_frames
        end = min(start + segment_frames, len(mono))
        try:
            result = detector.predict(mono[start:end], sample_rate)
            scores = result["scores"]
            if not scores:
                raise ValueError("The audio model returned no class scores.")
            if any(not math.isfinite(float(value)) or float(value) < 0 for value in scores.values()):
                raise ValueError("The audio model returned invalid class scores.")
        except Exception as exc:
            return {
                **base,
                "status": "failed",
                "stance": "could_not_check",
                "observation": None,
                "summary": f"Audio model inference failed ({type(exc).__name__}). No overall result is reported.",
            }, segment_results, {"duration_s": round(duration, 3), "sample_rate": sample_rate, "channels": channels, "decoder": decoder}

        weight = end - start
        labels.update(scores)
        for label, value in scores.items():
            weighted_scores[label] = weighted_scores.get(label, 0.0) + float(value) * weight
        weighted_total += weight
        segment_results.append({
            "index": index,
            "start_s": round(start / sample_rate, 3),
            "end_s": round(end / sample_rate, 3),
            "prediction": result["prediction"],
            "scores": scores,
        })

    averaged = {label: weighted_scores[label] / weighted_total for label in sorted(labels)}
    top_label = max(averaged, key=averaged.get)
    fake_labels = {label.lower() for label in s.audio_fake_labels}
    real_labels = {label.lower() for label in s.audio_real_labels}
    top_normalized = top_label.lower()
    stance = "supports_manipulation" if top_normalized in fake_labels else (
        "supports_authenticity" if top_normalized in real_labels else "inconclusive"
    )
    coverage = weighted_total / len(mono)
    complete = len(segment_results) == segment_count
    module = {
        **base,
        "status": "completed" if complete else "failed",
        "stance": stance if complete else "could_not_check",
        "observation": f"Top model label: {top_label}." if complete else None,
        "score": averaged if complete else None,
        "score_semantics": "Duration-weighted raw audio model class scores (uncalibrated); not verified probabilities.",
        "details": {
            **base["details"],
            "segments_analyzed": len(segment_results),
            "segments_total": segment_count,
            "evidence_coverage": round(coverage, 4),
        },
        "summary": (
            f"The configured model's top label is {top_label}. This is an unvalidated model interpretation, not proof of synthetic speech."
            if complete else "Audio inference stopped before the full recording was analyzed; no complete result is reported."
        ),
    }
    if not fake_labels and not real_labels and complete:
        module["limitations"] = [*base["limitations"], "Configure SATYAM_AUDIO_FAKE_LABELS and SATYAM_AUDIO_REAL_LABELS to map this model's labels; otherwise its output remains inconclusive."]
    return module, segment_results, {"duration_s": round(duration, 3), "sample_rate": sample_rate, "channels": channels}
