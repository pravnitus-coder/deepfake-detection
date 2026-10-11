"""Metadata findings. Missing metadata is NEVER treated as evidence of manipulation."""
from PIL import Image
from PIL.ExifTags import TAGS

STRONG_KEYS = {"parameters", "prompt", "workflow", "sd-metadata", "invokeai_metadata"}
GENERATOR_HINTS = ("stable diffusion", "midjourney", "dall-e", "dalle", "comfyui", "invokeai", "automatic1111", "firefly")


def result(**kw):
    base = dict(id="metadata", name="Metadata analysis", status="completed", method="Pillow EXIF/PNG-text reader",
                version="1", stance="inconclusive", observation=None, score=None, score_semantics=None, summary="",
                limitations=[], reliability="documented-limits", details={})
    base.update(kw)
    return base


def analyze_metadata(path: str) -> dict:
    limits = ["Metadata is easy to remove or forge; its absence is common after social-media re-uploads and proves nothing.",
              "C2PA / Content Credentials are not checked in this MVP."]
    try:
        with Image.open(path) as img:
            exif = {TAGS.get(k, str(k)): str(v)[:120] for k, v in img.getexif().items()}
            info = {str(k).lower(): v[:200] for k, v in img.info.items() if isinstance(v, str)}
            details = {"format": img.format, "width": img.width, "height": img.height, "mode": img.mode,
                       "has_exif": bool(exif), "camera": " ".join(x for x in (exif.get("Make"), exif.get("Model")) if x) or None,
                       "software": exif.get("Software"), "datetime": exif.get("DateTime"), "has_icc_profile": "icc_profile" in img.info}
    except Exception:
        return result(status="failed", stance="could_not_check", summary="Metadata could not be read from this file.", limitations=limits)

    blob = " ".join(info.values()).lower() + " " + (details["software"] or "").lower()
    if STRONG_KEYS & set(info) or any(h in blob for h in GENERATOR_HINTS):
        obs = "The file carries text fields typical of AI image generators."
        summary = obs + " Such fields can be copied into or stripped from other files, so this is a strong clue, not proof."
        stance = "supports_manipulation"
    elif details["has_exif"]:
        obs = "Camera/EXIF fields are present."
        summary = obs + " This is consistent with a camera file, but EXIF can be edited, so it does not prove authenticity."
        if details["software"]:
            summary += f" A Software tag is present ({details['software']}); it only shows the file passed through that program."
        stance = "inconclusive"
    else:
        obs = "No EXIF/camera metadata found."
        summary = obs + " This is common after sharing through messaging or social apps and is not evidence of manipulation."
        stance = "inconclusive"
    return result(stance=stance, observation=obs, summary=summary, limitations=limits, details=details)
