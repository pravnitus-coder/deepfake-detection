"""Typed response contract (documents the API; services build plain dicts matching these shapes)."""
from typing import Any, Optional
from pydantic import BaseModel


class ModuleResult(BaseModel):
    id: str
    name: str
    status: str  # completed | unavailable | failed
    stance: str  # supports_manipulation | supports_authenticity | inconclusive | could_not_check
    method: str
    version: str
    observation: Optional[str] = None
    score: Optional[Any] = None
    score_semantics: Optional[str] = None
    summary: str
    limitations: list[str]
    reliability: str

    details: dict[str, Any] = {}


class Fusion(BaseModel):
    assessment: str
    risk_indicator: str
    calibrated_probability: Optional[float] = None
    calibration_note: str
    explanation: str
    unavailable: list[dict]
    conflicts: list[dict]


class Investigation(BaseModel):
    id: str
    created_at: str
    kind: str
    file: dict
    modules: list[ModuleResult]
    fusion: Fusion
    frames: list[dict] = []
    audio_segments: list[dict] = []
    media_details: Optional[dict] = None
    processing_errors: list[str] = []
