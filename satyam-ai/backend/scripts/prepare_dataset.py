"""Build a labeled, multimodal CSV from an explicitly annotated local manifest.

Run from the project root with:
    python backend/scripts/prepare_dataset.py

The default input is dataset/annotations.csv. No media is downloaded, labels are
never inferred from filenames, and unavailable detector results remain blank.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import os
import pathlib
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
import soundfile as sf
from PIL import Image


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
MEDIA_TARGETS = {"image": 4000, "video": 3000, "audio": 3000}
LABELS = ("AUTHENTIC", "MANIPULATED", "AI_GENERATED", "UNKNOWN")
MEDIA_TYPES = ("image", "video", "audio")

COLUMNS = [
    "sample_id", "media_type", "file_name", "file_path", "file_extension",
    "file_size_bytes", "file_hash_sha256", "source_dataset", "source_url",
    "license", "split", "split_group", "authenticity_label", "manipulation_type",
    "is_manipulated", "is_fully_ai_generated", "label_source", "label_confidence",
    "image_width", "image_height", "color_mode", "mean_brightness", "contrast_score",
    "blur_score", "jpeg_compression_quality", "face_count", "face_manipulation_score",
    "image_ai_generation_score", "image_model_prediction", "image_model_name",
    "video_duration_seconds", "video_width", "video_height", "video_fps",
    "video_frame_count", "frames_analyzed", "suspicious_frame_ratio",
    "temporal_inconsistency_score", "lip_sync_anomaly_score", "video_model_prediction",
    "video_model_name", "audio_duration_seconds", "audio_sample_rate", "audio_channels",
    "audio_codec", "rms_energy", "zero_crossing_rate", "spectral_centroid",
    "spectral_bandwidth", "synthetic_speech_score", "voice_cloning_score",
    "audio_manipulation_score", "audio_model_prediction", "audio_model_name",
    "authentic_probability", "manipulated_probability", "ai_generated_probability",
    "prediction_confidence", "evidence_summary", "analysis_status",
    "analysis_timestamp", "feature_notes",
]

SCHEMA: list[tuple[str, str, str]] = [
    ("sample_id", "string", "Full SHA-256-derived ID; unique after duplicate-hash rejection."),
    ("media_type", "enum", "One of image, video, audio."),
    ("file_name", "string", "Original file name."),
    ("file_path", "string", "Resolved path to the actual local media file."),
    ("file_extension", "string", "Lowercase suffix from the actual path."),
    ("file_size_bytes", "integer", "Actual file size in bytes."),
    ("file_hash_sha256", "hex string", "SHA-256 of the actual file contents."),
    ("source_dataset", "string", "Dataset/provenance name supplied by the annotator."),
    ("source_url", "URL/string", "Source documentation or record URL, if available."),
    ("license", "string", "Applicable license or access terms supplied by the annotator."),
    ("split", "enum", "Deterministic group split: train, validation, or test."),
    ("split_group", "string", "Related-source group kept within one split; exact hash fallback if absent."),
    ("authenticity_label", "enum", "AUTHENTIC, MANIPULATED, AI_GENERATED, or UNKNOWN; from annotations."),
    ("manipulation_type", "string", "Source-documented manipulation method/type."),
    ("is_manipulated", "boolean/string", "AUTHENTIC=0, MANIPULATED=1, AI_GENERATED=0; blank for UNKNOWN."),
    ("is_fully_ai_generated", "boolean/string", "AI_GENERATED=1; other known labels=0; blank for UNKNOWN."),
    ("label_source", "string", "Annotation record or documented provenance; never inferred from filename."),
    ("label_confidence", "float [0,1]", "Source-provided confidence; blank if not supplied."),
    ("image_width", "integer", "Decoded image width in pixels."),
    ("image_height", "integer", "Decoded image height in pixels."),
    ("color_mode", "string", "Pillow decoded image color mode."),
    ("mean_brightness", "float", "Mean 8-bit grayscale intensity."),
    ("contrast_score", "float", "Standard deviation of 8-bit grayscale intensity."),
    ("blur_score", "float", "Variance of Laplacian; descriptive sharpness heuristic, not authenticity evidence."),
    ("jpeg_compression_quality", "float", "Unavailable: encoded JPEG quality is not reliably recoverable."),
    ("face_count", "integer", "OpenCV Haar-cascade face count; heuristic and not a manipulation detector."),
    ("face_manipulation_score", "float", "Unavailable unless a dedicated validated detector is supplied."),
    ("image_ai_generation_score", "float", "Raw configured model score for configured fake labels; uncalibrated."),
    ("image_model_prediction", "string", "Top raw label from configured image classifier."),
    ("image_model_name", "string", "Configured image model ID, when inference ran."),
    ("video_duration_seconds", "float", "Decoded container duration (frame count / FPS)."),
    ("video_width", "integer", "Decoded frame width in pixels."),
    ("video_height", "integer", "Decoded frame height in pixels."),
    ("video_fps", "float", "Container-reported frames per second."),
    ("video_frame_count", "integer", "Container-reported total frame count."),
    ("frames_analyzed", "integer", "Number of sampled video frames successfully decoded."),
    ("suspicious_frame_ratio", "float [0,1]", "Share of sampled frames flagged by configured image model; not a video probability."),
    ("temporal_inconsistency_score", "float", "Unavailable: no temporal detector is implemented."),
    ("lip_sync_anomaly_score", "float", "Unavailable: no lip-sync detector is implemented."),
    ("video_model_prediction", "string", "Frame-vote result from configured image model; not a temporal video model."),
    ("video_model_name", "string", "Configured image model ID used on sampled frames."),
    ("audio_duration_seconds", "float", "Decoded audio duration in seconds."),
    ("audio_sample_rate", "integer", "Decoded audio sample rate in Hz."),
    ("audio_channels", "integer", "Decoded audio channel count."),
    ("audio_codec", "string", "Decoder-reported container format and subtype."),
    ("rms_energy", "float", "Measured root-mean-square amplitude, normalized by decoder sample range."),
    ("zero_crossing_rate", "float", "Measured fraction of adjacent mono samples changing sign."),
    ("spectral_centroid", "float", "Mean FFT magnitude-weighted frequency in Hz."),
    ("spectral_bandwidth", "float", "Mean FFT magnitude-weighted bandwidth in Hz."),
    ("synthetic_speech_score", "float", "Unavailable unless a validated detector with this exact output exists."),
    ("voice_cloning_score", "float", "Unavailable unless a validated voice-cloning detector exists."),
    ("audio_manipulation_score", "float", "Unavailable unless a validated audio-manipulation detector exists."),
    ("audio_model_prediction", "string", "Top raw label from configured audio classifier; not mapped to authenticity."),
    ("audio_model_name", "string", "Configured audio model ID, when inference ran."),
    ("authentic_probability", "float [0,1]", "Only populated by a validated compatible three-class model; blank here."),
    ("manipulated_probability", "float [0,1]", "Only populated by a validated compatible three-class model; blank here."),
    ("ai_generated_probability", "float [0,1]", "Only populated by a validated compatible three-class model; blank here."),
    ("prediction_confidence", "float [0,1]", "Only populated by a calibrated and documented model; blank here."),
    ("evidence_summary", "string", "Short summary of measured features and actual model outputs."),
    ("analysis_status", "enum", "completed, partial, or failed for the requested extraction."),
    ("analysis_timestamp", "ISO-8601 UTC", "Time this pipeline processed the media."),
    ("feature_notes", "string", "Unavailable/unsupported feature reasons and detector caveats."),
]


class SampleError(ValueError):
    """A manifest row cannot safely be admitted to the output dataset."""


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as media:
        for chunk in iter(lambda: media.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(value: str, manifest_dir: pathlib.Path) -> pathlib.Path:
    if not value.strip():
        raise SampleError("missing file_path")
    path = pathlib.Path(value.strip()).expanduser()
    if not path.is_absolute():
        path = manifest_dir / path
    path = path.resolve()
    if not path.is_file():
        raise SampleError(f"media file does not exist: {path}")
    return path


def _metadata(row: dict[str, str], path: pathlib.Path) -> dict[str, Any]:
    media_type = row.get("media_type", "").strip().lower()
    if media_type not in MEDIA_TYPES:
        raise SampleError("media_type must be image, video, or audio")
    label = row.get("authenticity_label", "").strip().upper()
    if label not in LABELS:
        raise SampleError("authenticity_label must be AUTHENTIC, MANIPULATED, AI_GENERATED, or UNKNOWN")
    if not row.get("source_dataset", "").strip():
        raise SampleError("source_dataset is required")
    if label != "UNKNOWN" and not row.get("label_source", "").strip():
        raise SampleError("label_source is required for labeled samples")

    confidence_raw = row.get("label_confidence", "").strip()
    confidence: float | str = ""
    if confidence_raw:
        try:
            confidence = float(confidence_raw)
        except ValueError as exc:
            raise SampleError("label_confidence must be numeric in [0,1]") from exc
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise SampleError("label_confidence must be numeric in [0,1]")

    file_hash = sha256_file(path)
    explicit_group = row.get("split_group", "").strip()
    return {
        "sample_id": f"sha256:{file_hash}",
        "media_type": media_type,
        "file_name": path.name,
        "file_path": str(path),
        "file_extension": path.suffix.lower(),
        "file_size_bytes": path.stat().st_size,
        "file_hash_sha256": file_hash,
        "source_dataset": row["source_dataset"].strip(),
        "source_url": row.get("source_url", "").strip(),
        "license": row.get("license", "").strip(),
        "split_group": explicit_group or f"sha256:{file_hash}",
        "authenticity_label": label,
        "manipulation_type": row.get("manipulation_type", "").strip(),
        "is_manipulated": {"AUTHENTIC": 0, "MANIPULATED": 1, "AI_GENERATED": 0, "UNKNOWN": ""}[label],
        "is_fully_ai_generated": {"AUTHENTIC": 0, "MANIPULATED": 0, "AI_GENERATED": 1, "UNKNOWN": ""}[label],
        "label_source": row.get("label_source", "").strip(),
        "label_confidence": confidence,
    }


def _sample_image(row: dict[str, Any], detector: Any, fake_labels: set[str], run_models: bool) -> list[str]:
    notes = ["JPEG encoded quality is not recoverable reliably; field left blank.",
             "Face manipulation score unavailable: no dedicated validated detector is configured."]
    with Image.open(row["file_path"]) as image:
        image.load()
        gray = image.convert("L")
        array = np.asarray(gray)
        row.update(image_width=image.width, image_height=image.height, color_mode=image.mode,
                   mean_brightness=round(float(array.mean()), 6),
                   contrast_score=round(float(array.std()), 6))
        laplacian = cv2.Laplacian(array, cv2.CV_64F)
        row["blur_score"] = round(float(laplacian.var()), 6)
        try:
            cascade_path = pathlib.Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(str(cascade_path))
            if not cascade.empty():
                row["face_count"] = int(len(cascade.detectMultiScale(array, scaleFactor=1.1, minNeighbors=4)))
                notes.append("face_count uses OpenCV Haar cascade; heuristic and not ground truth.")
        except (AttributeError, cv2.error, OSError):
            notes.append("Face count unavailable: OpenCV Haar cascade was not available.")
        if run_models:
            if detector is None or not detector.status().get("ready"):
                notes.append("Image inference unavailable: no ready detector is configured.")
            else:
                try:
                    prediction = detector.predict(image)
                    scores = prediction.get("scores", {})
                    row["image_model_prediction"] = prediction.get("prediction", "")
                    row["image_model_name"] = detector.name
                    mapped_scores = [float(value) for name, value in scores.items() if str(name).lower() in fake_labels]
                    if mapped_scores:
                        row["image_ai_generation_score"] = max(mapped_scores)
                        notes.append("Image model score is raw and uncalibrated, not an authenticity probability.")
                    else:
                        notes.append("Image classifier labels did not match configured fake-label mapping; score left blank.")
                except Exception as exc:
                    notes.append(f"Image model inference failed ({type(exc).__name__}); no prediction recorded.")
    return notes


def _sample_video(row: dict[str, Any], detector: Any, run_models: bool, max_frames: int = 12) -> list[str]:
    notes = ["Temporal inconsistency score unavailable: no temporal detector is implemented.",
             "Lip-sync anomaly score unavailable: no lip-sync detector is implemented."]
    cap = cv2.VideoCapture(row["file_path"])
    if not cap.isOpened():
        raise SampleError("video decoder could not open file")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
            raise SampleError("video decoder returned invalid dimensions, FPS, or frame count")
        duration = frame_count / fps
        row.update(video_duration_seconds=round(duration, 6), video_width=width, video_height=height,
                   video_fps=round(fps, 6), video_frame_count=frame_count)
        sample_count = min(max_frames, frame_count)
        positions = sorted(set(int(i * (frame_count - 1) / max(1, sample_count - 1)) for i in range(sample_count)))
        decoded = scored = flagged = 0
        model_failed = False
        for position in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, position)
            ok, bgr = cap.read()
            if not ok:
                continue
            decoded += 1
            if run_models and detector is not None and detector.status().get("ready"):
                from PIL import Image as PILImage
                try:
                    prediction = detector.predict(PILImage.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
                    flagged += int(bool(prediction.get("flagged")))
                    scored += 1
                except Exception:
                    model_failed = True
        row["frames_analyzed"] = decoded
        if model_failed:
            notes.append("Video frame inference failed for one or more sampled frames; only successful predictions were counted.")
        if run_models and detector is not None and detector.status().get("ready"):
            row["video_model_name"] = detector.name
            if scored:
                ratio = flagged / scored
                row["suspicious_frame_ratio"] = round(ratio, 6)
                row["video_model_prediction"] = "MANIPULATED" if ratio > 0.5 else "AUTHENTIC" if ratio < 0.5 else "UNKNOWN"
                notes.append("Frame flag ratio is a sampled-frame statistic, not a video probability or temporal analysis.")
        elif run_models:
            notes.append("Video frame inference unavailable: no ready image detector is configured.")
    finally:
        cap.release()
    return notes


def _sample_audio(row: dict[str, Any], detector: Any, run_models: bool) -> list[str]:
    notes = ["Synthetic-speech, voice-cloning, and audio-manipulation scores unavailable: no validated detectors with these outputs are configured."]
    total_samples = crossings = 0
    last_sample: float | None = None
    square_sum = centroid_sum = bandwidth_sum = spectral_weight = 0.0
    with sf.SoundFile(row["file_path"]) as audio:
        sample_rate, channels, frames = audio.samplerate, audio.channels, len(audio)
        if sample_rate <= 0 or channels <= 0:
            raise SampleError("audio decoder returned invalid sample rate or channel count")
        for block in audio.blocks(blocksize=8192, dtype="float32", always_2d=True):
            mono = block.mean(axis=1)
            if mono.size == 0:
                continue
            total_samples += mono.size
            square_sum += float(np.square(mono, dtype=np.float64).sum())
            crossings += int(np.count_nonzero(np.signbit(mono[1:]) != np.signbit(mono[:-1])))
            if last_sample is not None and mono.size and (last_sample < 0) != (mono[0] < 0):
                crossings += 1
            if mono.size:
                last_sample = float(mono[-1])
            if mono.size > 1:
                spectrum = np.abs(np.fft.rfft(mono * np.hanning(mono.size)))
                frequencies = np.fft.rfftfreq(mono.size, d=1 / sample_rate)
                weight = float(spectrum.sum())
                if weight > 0:
                    centroid = float(np.dot(frequencies, spectrum) / weight)
                    bandwidth = float(np.dot(np.abs(frequencies - centroid), spectrum) / weight)
                    centroid_sum += centroid * weight
                    bandwidth_sum += bandwidth * weight
                    spectral_weight += weight
        if total_samples == 0:
            raise SampleError("audio file contains no decodable samples")
        row.update(audio_duration_seconds=round(frames / sample_rate, 6),
                   audio_sample_rate=sample_rate, audio_channels=channels,
                   audio_codec=f"{audio.format}/{audio.subtype}",
                   rms_energy=round(math.sqrt(square_sum / total_samples), 9),
                   zero_crossing_rate=round(crossings / max(1, total_samples - 1), 9))
        if spectral_weight:
            row["spectral_centroid"] = round(centroid_sum / spectral_weight, 6)
            row["spectral_bandwidth"] = round(bandwidth_sum / spectral_weight, 6)
    if run_models:
        if detector is None or not detector.status().get("ready"):
            notes.append("Audio inference unavailable: no ready detector is configured.")
        else:
            accumulated: dict[str, list[float]] = defaultdict(list)
            try:
                with sf.SoundFile(row["file_path"]) as audio:
                    segment_size = max(sample_rate, sample_rate * 10)
                    while True:
                        segment = audio.read(frames=segment_size, dtype="float32", always_2d=True)
                        if not len(segment):
                            break
                        scores = detector.predict(segment.mean(axis=1), sample_rate).get("scores", {})
                        for name, score in scores.items():
                            accumulated[str(name)].append(float(score))
                if accumulated:
                    means = {name: sum(values) / len(values) for name, values in accumulated.items()}
                    row["audio_model_prediction"] = max(means, key=means.get)
                    row["audio_model_name"] = detector.name
                    notes.append("Audio model output is the top raw label averaged across 10-second segments; not an authenticity probability.")
            except Exception as exc:
                notes.append(f"Audio model inference failed ({type(exc).__name__}); no prediction recorded.")
    return notes


def _split(group: str) -> str:
    value = int(hashlib.sha256(group.encode("utf-8")).hexdigest()[:8], 16) % 100
    return "train" if value < 70 else "validation" if value < 85 else "test"


def _prepare_one(raw: dict[str, str], manifest_dir: pathlib.Path, models: tuple[Any, Any] | None) -> dict[str, Any]:
    path = _resolve_path(raw.get("file_path", ""), manifest_dir)
    row = _metadata(raw, path)
    row["analysis_timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notes: list[str] = []
    image_detector = models[0] if models else None
    audio_detector = models[1] if models else None
    run_models = models is not None
    if row["media_type"] == "image":
        notes.extend(_sample_image(row, image_detector, _configured_fake_labels(), run_models))
    elif row["media_type"] == "video":
        notes.extend(_sample_video(row, image_detector, run_models))
    else:
        notes.extend(_sample_audio(row, audio_detector, run_models))
    row["split"] = _split(row["split_group"])
    row["authentic_probability"] = ""
    row["manipulated_probability"] = ""
    row["ai_generated_probability"] = ""
    row["prediction_confidence"] = ""
    row["evidence_summary"] = "Measured media features; no calibrated authenticity probabilities are available."
    row["analysis_status"] = "partial"
    row["feature_notes"] = " ".join(notes)
    for column in COLUMNS:
        row.setdefault(column, "")
    return row


def _configured_fake_labels() -> set[str]:
    return {label.strip().lower() for label in os.environ.get(
        "SATYAM_HF_FAKE_LABELS", "artificial,fake,ai,ai-generated,generated"
    ).split(",") if label.strip()}


def _load_models() -> tuple[Any, Any] | None:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from app.models.model_registry import get_audio_detector, get_detector
    return get_detector(), get_audio_detector()


def _select_target_rows(rows: list[dict[str, Any]], target_total: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    targets = dict(MEDIA_TARGETS)
    if target_total != sum(targets.values()):
        # Preserve the requested modality proportions for custom smaller test runs.
        targets = {kind: round(target_total * count / sum(MEDIA_TARGETS.values())) for kind, count in MEDIA_TARGETS.items()}
        targets["audio"] += target_total - sum(targets.values())
    for media_type in MEDIA_TYPES:
        candidates = [row for row in rows if row["media_type"] == media_type]
        by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in candidates:
            by_label[row["authenticity_label"]].append(row)
        for group in by_label.values():
            group.sort(key=lambda item: item["file_hash_sha256"])
        labels = [label for label in LABELS if label != "UNKNOWN" and by_label[label]]
        if by_label["UNKNOWN"]:
            labels.append("UNKNOWN")
        quota = targets[media_type]
        taken = 0
        while taken < quota and labels:
            remaining_labels = []
            for label in labels:
                if by_label[label] and taken < quota:
                    selected.append(by_label[label].pop(0))
                    taken += 1
                if by_label[label]:
                    remaining_labels.append(label)
            labels = remaining_labels
    return selected, targets


def _write_csv(path: pathlib.Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts = Counter((row["media_type"], row["authenticity_label"]) for row in rows)
    summaries: list[dict[str, Any]] = []
    for kind in MEDIA_TYPES:
        summaries.append({"summary_type": "MEDIA_TYPE", "media_type": kind, "authenticity_label": "",
                         "manipulation_type": "", "record_count": sum(n for (m, _), n in counts.items() if m == kind)})
    for label in LABELS:
        summaries.append({"summary_type": "AUTHENTICITY_LABEL", "media_type": "", "authenticity_label": label,
                         "manipulation_type": "", "record_count": sum(n for (_, l), n in counts.items() if l == label)})
    manipulation_counts = Counter(
        (row["media_type"], row["authenticity_label"], row["manipulation_type"])
        for row in rows if row.get("manipulation_type")
    )
    for (kind, label, manipulation), count in sorted(manipulation_counts.items()):
        summaries.append({"summary_type": "MANIPULATION_TYPE", "media_type": kind,
                         "authenticity_label": label, "manipulation_type": manipulation,
                         "record_count": count})
    summaries.append({"summary_type": "TOTAL", "media_type": "", "authenticity_label": "",
                     "manipulation_type": "", "record_count": len(rows)})
    return summaries


def _write_report(
    path: pathlib.Path, manifest: pathlib.Path, raw_rows: int, rows: list[dict[str, Any]],
    issues: list[str], rejected_duplicates: int, conflicting_hashes: int, targets: dict[str, int],
    requested_total: int,
) -> None:
    counts_media = Counter(row["media_type"] for row in rows)
    counts_labels = Counter((row["media_type"], row["authenticity_label"]) for row in rows)
    counts_splits = Counter(row["split"] for row in rows)
    group_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        group_splits[row["split_group"]].add(row["split"])
    leakage_groups = sum(len(splits) > 1 for splits in group_splits.values())
    bad_label_flags = sum(
        row["is_manipulated"] != {"AUTHENTIC": 0, "MANIPULATED": 1, "AI_GENERATED": 0, "UNKNOWN": ""}[row["authenticity_label"]]
        or row["is_fully_ai_generated"] != {"AUTHENTIC": 0, "MANIPULATED": 0, "AI_GENERATED": 1, "UNKNOWN": ""}[row["authenticity_label"]]
        for row in rows
    )
    missing_files = sum(not pathlib.Path(row["file_path"]).is_file() for row in rows)
    missing = {column: sum(not str(row.get(column, "")).strip() for row in rows)
               for column in COLUMNS if rows and any(not str(row.get(column, "")).strip() for row in rows)}
    with path.open("w", encoding="utf-8", newline="\n") as report:
        report.write("SATYAM AI dataset validation report\n")
        report.write(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")
        report.write(f"Manifest: {manifest}\n")
        report.write(f"Manifest rows read: {raw_rows}\n")
        report.write(f"Valid unique output records: {len(rows)}\n")
        report.write(f"Requested target: {requested_total}\n")
        report.write(f"Shortfall to target: {max(0, requested_total - len(rows))}\n")
        report.write("Status: " + ("COMPLETE" if len(rows) == requested_total else "INCOMPLETE; no records were fabricated") + "\n")
        report.write(f"Exact duplicate rows discarded: {rejected_duplicates}\n")
        report.write(f"Conflicting-label duplicate hashes excluded: {conflicting_hashes}\n\n")
        report.write("Validation checks:\n")
        if rows:
            report.write(f"  Unique sample IDs: {'PASS' if len({row['sample_id'] for row in rows}) == len(rows) else 'FAIL'}\n")
            report.write(f"  Unique SHA-256 hashes: {'PASS' if len({row['file_hash_sha256'] for row in rows}) == len(rows) else 'FAIL'}\n")
            report.write(f"  Referenced media files exist: {'PASS' if missing_files == 0 else 'FAIL'} ({missing_files} missing)\n")
            report.write(f"  Label/boolean taxonomy consistency: {'PASS' if bad_label_flags == 0 else 'FAIL'} ({bad_label_flags} inconsistent)\n")
            report.write(f"  Split groups spanning multiple splits: {'PASS' if leakage_groups == 0 else 'FAIL'} ({leakage_groups} groups)\n")
        else:
            report.write("  Unique IDs/hashes, file paths, label consistency, and split leakage: N/A (no records)\n")
        report.write("  Feature reproducibility across independent reruns: NOT TESTED\n")
        report.write("  Near-duplicate detection: NOT RUN\n\n")
        if not raw_rows:
            report.write("Input limitation: no annotation rows or verified local media samples were supplied.\n\n")
        report.write("Records by media type (target):\n")
        for kind in MEDIA_TYPES:
            report.write(f"  {kind}: {counts_media[kind]} / {targets[kind]}\n")
        report.write("\nRecords by modality and authenticity label:\n")
        for kind in MEDIA_TYPES:
            for label in LABELS:
                report.write(f"  {kind}, {label}: {counts_labels[(kind, label)]}\n")
        report.write("\nRecords by split:\n")
        for split_name in ("train", "validation", "test"):
            split_count = counts_splits[split_name]
            pct = 100 * split_count / len(rows) if rows else 0.0
            report.write(f"  {split_name}: {split_count} ({pct:.2f}%)\n")
        report.write("\nMissing-value counts (blank output fields):\n")
        if missing:
            for column, count in missing.items():
                report.write(f"  {column}: {count}/{len(rows)}\n")
        else:
            report.write("  No data rows; all feature/count fields are not applicable.\n")
        report.write("\nQuality checks and limitations:\n")
        report.write("  Labels are accepted only from the manifest; filenames are never used to infer ground truth.\n")
        report.write("  Exact SHA-256 duplicates are removed; conflicting labels for one hash exclude that hash.\n")
        report.write("  Near-duplicate detection is not run. Supply split_group for related originals/derivatives to prevent leakage.\n")
        report.write("  Split is deterministic by split_group; if omitted, exact hash is used and related media may leak across splits.\n")
        report.write("  Probability, calibration, temporal, lip-sync, voice-cloning, and manipulation scores remain blank without validated compatible models.\n")
        report.write("  Audio energy/spectral statistics are measurements, not evidence that speech is synthetic.\n")
        report.write("  CSV labels and measurements are separate; do not include labels, paths, hashes, source IDs, or split metadata as model features.\n")
        report.write("  Processing uses the locally installed Pillow, OpenCV, NumPy, and SoundFile versions; record environment versions for strict reproducibility.\n")
        if not manifest.is_file():
            report.write(f"\nInput limitation: annotation manifest does not exist: {manifest}\n")
        if issues:
            report.write(f"\nRejected/failed rows ({len(issues)}; first 100 shown):\n")
            for issue in issues[:100]:
                report.write(f"  {issue}\n")
        report.write("\nPublic candidate sources reviewed; none were downloaded or used in this output:\n")
        report.write("  FaceForensics++: https://github.com/ondyari/FaceForensics (request/access workflow; manipulated facial videos, not fully-AI-generated class).\n")
        report.write("  DFDC: https://ai.meta.com/datasets/dfdc/ (AWS account/access conditions; authentic and manipulated videos).\n")
        report.write("  Celeb-DF: https://github.com/yuezunli/celeb-deepfakeforensics (access form and terms of use; original and synthesized videos).\n")
        report.write("  GenImage: https://github.com/GenImage-Dataset/GenImage (AI-generated and natural image benchmark; verify applicable terms before use).\n")
        report.write("  WaveFake: https://github.com/RUB-SysSec/WaveFake (synthetic audio benchmark; verify dataset license/conditions before use).\n")
        report.write("  Confirm each dataset's current license, access approval, source annotations, and redistribution rights before processing or sharing.\n")


def build_dataset(manifest: pathlib.Path, output_dir: pathlib.Path, target_total: int = 10000,
                  run_models: bool = False) -> tuple[int, list[str]]:
    manifest = manifest.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict[str, str]] = []
    issues: list[str] = []
    if manifest.is_file():
        with manifest.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source)
            if not reader.fieldnames or "file_path" not in reader.fieldnames:
                raise ValueError("Manifest must be a CSV with a file_path header.")
            for entry in reader:
                raw_rows.append({key: (value or "") for key, value in entry.items() if key is not None})

    models = _load_models() if run_models else None
    valid_by_hash: dict[str, dict[str, Any]] = {}
    rejected_duplicates = 0
    conflict_hashes: set[str] = set()
    for index, raw in enumerate(raw_rows, start=2):
        try:
            prepared = _prepare_one(raw, manifest.parent, models)
            file_hash = prepared["file_hash_sha256"]
            if file_hash in valid_by_hash:
                if valid_by_hash[file_hash]["authenticity_label"] != prepared["authenticity_label"]:
                    conflict_hashes.add(file_hash)
                    valid_by_hash.pop(file_hash, None)
                    issues.append(f"row {index}: duplicate content has conflicting authenticity labels; hash excluded")
                elif file_hash not in conflict_hashes:
                    rejected_duplicates += 1
                continue
            if file_hash not in conflict_hashes:
                valid_by_hash[file_hash] = prepared
        except (SampleError, OSError, ValueError, RuntimeError, cv2.error, sf.SoundFileRuntimeError) as exc:
            issues.append(f"row {index}: {type(exc).__name__}: {exc}")

    candidates = list(valid_by_hash.values())
    selected, targets = _select_target_rows(candidates, target_total)
    if len(candidates) > len(selected):
        issues.append(f"{len(candidates) - len(selected)} valid samples excluded by modality target caps.")
    selected.sort(key=lambda item: (item["media_type"], item["file_hash_sha256"]))

    _write_csv(output_dir / "satyam_ai_dataset.csv", COLUMNS, selected)
    _write_csv(output_dir / "dataset_schema.csv", ["column_name", "data_type", "description"],
               [{"column_name": name, "data_type": kind, "description": description}
                for name, kind, description in SCHEMA])
    _write_csv(output_dir / "dataset_summary.csv",
               ["summary_type", "media_type", "authenticity_label", "manipulation_type", "record_count"],
               _summary_rows(selected))
    _write_report(output_dir / "dataset_validation_report.txt", manifest, len(raw_rows), selected,
                  issues, rejected_duplicates, len(conflict_hashes), targets, target_total)
    return len(selected), issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=pathlib.Path, default=PROJECT_ROOT / "dataset" / "annotations.csv",
                        help="CSV annotations manifest (default: dataset/annotations.csv)")
    parser.add_argument("--output-dir", type=pathlib.Path, default=PROJECT_ROOT,
                        help="Directory for the four requested deliverables (default: project root)")
    parser.add_argument("--target-rows", type=int, default=10000, help="Requested total row target (default: 10000)")
    parser.add_argument("--run-configured-models", action="store_true",
                        help="Run currently configured image/audio adapters; raw model outputs remain uncalibrated.")
    args = parser.parse_args()
    if args.target_rows < 0:
        parser.error("--target-rows must be non-negative")
    try:
        count, issues = build_dataset(args.manifest, args.output_dir, args.target_rows, args.run_configured_models)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Dataset preparation failed: {exc}\n")
    status = "COMPLETE" if count == args.target_rows else f"INCOMPLETE ({count}/{args.target_rows})"
    print(f"{status}: wrote {count} actual records; see dataset_validation_report.txt")
    if issues:
        print(f"Rows with warnings/errors or cap exclusions: {len(issues)}")
    return 0 if count == args.target_rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
