"""Detector adapter. Swap the model via env vars or add a Detector subclass; API and UI do not change.
If no model can load, the detector reports itself as unavailable. It NEVER returns made-up scores."""
from abc import ABC, abstractmethod
from functools import lru_cache
import math
from app.core.config import get_settings


class Detector(ABC):
    name = "none"
    version = "n/a"

    @abstractmethod
    def status(self) -> dict: ...

    @abstractmethod
    def predict(self, image) -> dict:
        """Return {prediction, scores:{label:float}, flagged:bool}. Raise on failure."""


class UnavailableDetector(Detector):
    def __init__(self, reason):
        self.reason = reason

    def status(self):
        return {"ready": False, "name": self.name, "version": self.version, "reason": self.reason}

    def predict(self, image):
        raise RuntimeError(self.reason)


class HFImageDetector(Detector):
    """Wraps a Hugging Face image-classification model whose labels include an 'AI/fake' class."""

    def __init__(self, model_id, fake_labels, revision=""):
        from transformers import pipeline  # optional dependency
        self.name = model_id
        self.version = revision[:12] if revision else "revision not pinned"
        self.fake_labels = fake_labels
        self.pipe = pipeline("image-classification", model=model_id, revision=revision or None, top_k=None)

    def status(self):
        return {"ready": True, "name": self.name, "version": self.version, "reason": None}

    def predict(self, image):
        out = self.pipe(image.convert("RGB"))
        scores = {o["label"]: float(o["score"]) for o in out}
        top = max(scores, key=scores.get)
        return {"prediction": top, "scores": scores, "flagged": top.lower() in self.fake_labels}


class HFAudioDetector:
    """Optional Hugging Face audio-classification adapter; it does not imply a model is forensic."""

    def __init__(self, model_id, revision=""):
        from transformers import pipeline
        self.name = model_id
        self.version = revision[:12] if revision else "revision not pinned"
        self.pipe = pipeline("audio-classification", model=model_id, revision=revision or None, top_k=None)

    def status(self):
        return {"ready": True, "name": self.name, "version": self.version, "reason": None}

    def predict(self, samples, sample_rate):
        outputs = self.pipe({"raw": samples, "sampling_rate": sample_rate})
        scores = {str(item["label"]): float(item["score"]) for item in outputs}
        if not scores or any(not math.isfinite(value) or value < 0 for value in scores.values()):
            raise ValueError("The audio model returned invalid class scores.")
        return {"prediction": max(scores, key=scores.get), "scores": scores}


@lru_cache(maxsize=1)
def get_detector() -> Detector:
    s = get_settings()
    if not s.hf_model:
        return UnavailableDetector("No model configured. Set SATYAM_HF_MODEL (see README) and install requirements-ml.txt.")
    try:
        return HFImageDetector(s.hf_model, s.hf_fake_labels, s.hf_model_revision)
    except Exception as e:  # missing torch/transformers, no network, bad model id
        return UnavailableDetector(f"Model '{s.hf_model}' could not be loaded: {type(e).__name__}.")


@lru_cache(maxsize=1)
def get_audio_detector():
    s = get_settings()
    if not s.audio_model:
        return UnavailableDetector("No audio detector configured. Set SATYAM_AUDIO_MODEL and install requirements-ml.txt.")
    try:
        return HFAudioDetector(s.audio_model, s.audio_model_revision)
    except Exception as e:
        return UnavailableDetector(f"Audio model '{s.audio_model}' could not be loaded: {type(e).__name__}.")
