from collections import defaultdict, deque
import time
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from app.core.config import get_settings
from app.services import auth

router = APIRouter()
_hits: dict[str, deque[float]] = defaultdict(deque)


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _limit_auth(request: Request) -> None:
    now = time.monotonic()
    key = request.client.host if request.client else "unknown"
    hits = _hits[key]
    while hits and now - hits[0] >= 60:
        hits.popleft()
    if len(hits) >= 10:
        raise HTTPException(429, "Too many authentication attempts. Wait a minute and try again.")
    hits.append(now)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    return token.strip() if separator and scheme.lower() == "bearer" and token.strip() else None


def require_user(authorization: str | None = Header(default=None)) -> str:
    user_id = auth.authenticate(bearer_token(authorization))
    if not user_id:
        raise HTTPException(401, "Sign in to continue.")
    return user_id


@router.post("/auth/register", status_code=201)
def register(credentials: Credentials, request: Request):
    _limit_auth(request)
    try:
        user_id, token = auth.register(credentials.username, credentials.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"user_id": user_id, "username": credentials.username.strip().lower(), "access_token": token,
            "token_type": "bearer", "expires_in": auth.SESSION_HOURS * 3600}


@router.post("/auth/login")
def login(credentials: Credentials, request: Request):
    _limit_auth(request)
    result = auth.login(credentials.username, credentials.password)
    if not result:
        raise HTTPException(401, "Username or password is incorrect.")
    user_id, token = result
    return {"user_id": user_id, "username": credentials.username.strip().lower(), "access_token": token,
            "token_type": "bearer", "expires_in": auth.SESSION_HOURS * 3600}


@router.get("/auth/me")
def current_user(user_id: str = Depends(require_user)):
    return {"user_id": user_id}


@router.post("/auth/logout", status_code=204)
def logout(authorization: str | None = Header(default=None), user_id: str = Depends(require_user)):
    del user_id
    auth.logout(bearer_token(authorization))
    return None
