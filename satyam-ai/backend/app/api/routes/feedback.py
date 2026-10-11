"""Feedback API endpoints for real user evaluation."""
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Request
from app.api.routes.auth import bearer_token
from app.db import database
from app.schemas.feedback import FeedbackCreate, FeedbackResponse
from app.services import auth

router = APIRouter()
_hits = defaultdict(deque)


def _rate_limit_feedback(request: Request):
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= 5:  # Max 5 submissions per minute per IP to prevent spam
        raise HTTPException(429, "Too many feedback submissions. Please wait a minute before submitting again.")
    q.append(now)


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(body: FeedbackCreate, request: Request, authorization: str | None = Header(default=None)):
    _rate_limit_feedback(request)
    token = bearer_token(authorization)
    user_id = auth.authenticate(token) if token else None

    feed_id = database.save_feedback(body.model_dump(), user_id=user_id)
    return FeedbackResponse(
        id=feed_id,
        message="Thank you! Your feedback has been recorded safely.",
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/feedback")
def get_feedback(limit: int = 50, authorization: str | None = Header(default=None)):
    token = bearer_token(authorization)
    user_id = auth.authenticate(token) if token else None
    if not user_id:
        raise HTTPException(401, "Sign in to view submitted feedback.")
    return database.list_feedback(limit=min(limit, 100))
