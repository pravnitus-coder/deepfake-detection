"""Visual-model and integrity modules for one image (also used per video frame)."""
import io
import numpy as np
from PIL import Image
from app.models.model_registry import Detector


def visual_module(img: Image.Image, detector: Detector) -> dict:
    st = detector.status()
    m = dict(id="ai_model", name="AI-generated content model", method=st["name"], version=st["version"],
             score=None, score_semantics=None, reliability="unvalidated",
             limitations=["Pretrained classifiers can fail on new generators, screenshots, heavy compression and unusual faces.",
                          "This project has not validated the model on its own data (see scripts/evaluate.py).",
                          "No suspicious-region overlay: the model gives a whole-image prediction, not localization."])
    if not st["ready"]:
        return {**m, "status": "unavailable", "stance": "could_not_check", "observation": None,
                "summary": f"Not run. {st['reason']}"}
    try:
        p = detector.predict(img)
    except Exception as e:
        return {**m, "status": "failed", "stance": "could_not_check", "observation": None,
                "summary": f"Inference failed ({type(e).__name__}). No result is reported."}
    flagged = p["flagged"]
    return {**m, "status": "completed", "stance": "supports_manipulation" if flagged else "supports_authenticity",
            "observation": f"Top label: {p['prediction']}", "score": p["scores"],
            "score_semantics": "Raw per-label model output (uncalibrated). Not a probability that the image is fake.",
            "summary": "The model's top label suggests the image may be AI-generated." if flagged
            else "The model's top label does not indicate AI generation. This is weak evidence of authenticity only."}


def ela_stats(img: Image.Image):
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, "JPEG", quality=90)
    buf.seek(0)
    again = Image.open(buf).convert("RGB")
    diff = np.abs(np.asarray(rgb, dtype=np.int16) - np.asarray(again, dtype=np.int16))
    return float(diff.mean()), float(np.percentile(diff, 99))


def integrity_module(img: Image.Image) -> dict:
    m = dict(id="integrity", name="Image integrity", method="Error-level analysis (summary statistics)", version="1",
             score=None, score_semantics=None, reliability="low",
             limitations=["Error-level analysis is a weak heuristic; re-saving, resizing and filters all change it.",
                          "Compression artifacts alone do not prove an image is fake.", "No localized overlay is produced."])
    if img.format != "JPEG":
        return {**m, "status": "unavailable", "stance": "could_not_check", "observation": None,
                "summary": "Error-level analysis only applies to JPEG files, so there is no integrity result for this format."}
    try:
        mean, p99 = ela_stats(img)
    except Exception:
        return {**m, "status": "failed", "stance": "could_not_check", "observation": None, "summary": "Integrity check failed."}
    return {**m, "status": "completed", "stance": "inconclusive",
            "observation": f"Recompression residual: mean {mean:.2f}, 99th percentile {p99:.1f} (8-bit scale).",
            "score": {"ela_mean": mean, "ela_p99": p99}, "score_semantics": "Descriptive statistics, not a manipulation score.",
            "summary": "We measured how the file reacts to recompression. Without a validated threshold this is an observation only and supports neither side."}
