"""Feedback schema for Challenge Card 2 user evaluation."""
from typing import Literal, Optional
from pydantic import BaseModel, Field


class FeedbackCreate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=100)
    role: Optional[Literal["Student", "Developer", "Researcher", "Journalist", "Other"]] = None
    rating: int = Field(ge=1, le=5, description="Overall experience rating between 1 and 5 stars")
    worked_as_expected: Optional[Literal["yes", "partially", "no"]] = None
    liked: Optional[str] = Field(default="", max_length=2000)
    confusing: Optional[str] = Field(default="", max_length=2000)
    feature_to_improve: Optional[str] = Field(default="", max_length=2000)
    bugs: Optional[str] = Field(default="", max_length=2000)
    suggestions: Optional[str] = Field(default="", max_length=2000)
    consent_to_publish: bool = Field(default=False)


class FeedbackResponse(BaseModel):
    id: str
    message: str
    created_at: str
