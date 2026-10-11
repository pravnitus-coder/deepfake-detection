"""Single-instance account authentication for uploads and analysis APIs."""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from app.db.database import conn

SESSION_HOURS = 12
PASSWORD_ITERATIONS = 310_000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_hash(password: str, salt: bytes | None = None, iterations: int = PASSWORD_ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${derived.hex()}"


# Precomputed dummy hash to prevent user-enumeration timing attacks during failed logins
_DUMMY_HASH = _password_hash("dummy_constant_time_protection_password", b"\x00" * 16, PASSWORD_ITERATIONS)


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_str, salt_hex, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_str)
        if iterations < 100_000:
            return False
        salt = bytes.fromhex(salt_hex)
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived.hex(), expected)
    except (ValueError, TypeError):
        return False


def register(username: str, password: str) -> tuple[str, str]:
    normalized = username.strip().lower()
    if not 3 <= len(normalized) <= 32 or not all(c.isalnum() or c in "_-" for c in normalized):
        raise ValueError("Username must be 3-32 letters, numbers, underscores, or hyphens.")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters.")
    user_id, token, now = str(uuid.uuid4()), secrets.token_urlsafe(32), _now()
    with conn() as database:
        if database.execute("SELECT 1 FROM users WHERE username=?", (normalized,)).fetchone():
            raise ValueError("That username is already registered.")
        database.execute(
            "INSERT INTO users(id, username, password_hash, created_at) VALUES(?,?,?,?)",
            (user_id, normalized, _password_hash(password), now.isoformat()),
        )
        database.execute(
            "INSERT INTO auth_sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (_token_hash(token), user_id, (now + timedelta(hours=SESSION_HOURS)).isoformat(), now.isoformat()),
        )
    return user_id, token


def login(username: str, password: str) -> tuple[str, str] | None:
    normalized = username.strip().lower()
    with conn() as database:
        row = database.execute("SELECT id, password_hash FROM users WHERE username=?", (normalized,)).fetchone()
        if not row:
            # Timing attack mitigation: run password verification with dummy hash
            _verify_password(password, _DUMMY_HASH)
            return None
        if not _verify_password(password, row[1]):
            return None
        token, now = secrets.token_urlsafe(32), _now()
        database.execute(
            "INSERT INTO auth_sessions(token_hash,user_id,expires_at,created_at) VALUES(?,?,?,?)",
            (_token_hash(token), row[0], (now + timedelta(hours=SESSION_HOURS)).isoformat(), now.isoformat()),
        )
    return row[0], token


def authenticate(token: str | None) -> str | None:
    if not token:
        return None
    token_hash = _token_hash(token)
    with conn() as database:
        row = database.execute(
            "SELECT user_id, expires_at FROM auth_sessions WHERE token_hash=?", (token_hash,)
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row[1]) <= _now():
            database.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))
            return None
        return str(row[0])


def logout(token: str | None) -> None:
    if not token:
        return
    with conn() as database:
        database.execute("DELETE FROM auth_sessions WHERE token_hash=?", (_token_hash(token),))


def cleanup_expired_sessions() -> int:
    now = _now().isoformat()
    with conn() as database:
        return database.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,)).rowcount
