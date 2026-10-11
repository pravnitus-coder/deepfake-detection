import json
import os
import pathlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from app.core.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auth_sessions(
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires_at ON auth_sessions(expires_at);

CREATE TABLE IF NOT EXISTS investigations(
    id TEXT PRIMARY KEY,
    created_at TEXT,
    kind TEXT,
    sha256 TEXT,
    size_bytes INTEGER,
    mime TEXT,
    assessment TEXT,
    risk TEXT,
    result_json TEXT,
    user_id TEXT REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_investigations_user_created ON investigations(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS module_results(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    module_id TEXT,
    status TEXT,
    stance TEXT,
    method TEXT,
    version TEXT,
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_module_results_inv_id ON module_results(investigation_id);

CREATE TABLE IF NOT EXISTS frame_findings(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    idx INTEGER,
    time_s REAL,
    stance TEXT,
    data_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_frame_findings_inv_id ON frame_findings(investigation_id);

CREATE TABLE IF NOT EXISTS reports(
    id TEXT PRIMARY KEY,
    investigation_id TEXT REFERENCES investigations(id) ON DELETE CASCADE,
    created_at TEXT,
    report_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_inv_id ON reports(investigation_id);

CREATE TABLE IF NOT EXISTS uploads(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    declared_mime TEXT NOT NULL,
    expected_size INTEGER NOT NULL,
    expected_sha256 TEXT NOT NULL,
    chunk_size INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    analysis_id TEXT,
    simulation_json TEXT,
    FOREIGN KEY(analysis_id) REFERENCES investigations(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS uploads_owner_status ON uploads(user_id, status);
CREATE INDEX IF NOT EXISTS idx_uploads_expires_at ON uploads(expires_at);

CREATE TABLE IF NOT EXISTS upload_chunks(
    upload_id TEXT NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    stored_at TEXT NOT NULL,
    PRIMARY KEY(upload_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS feedback(
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    name TEXT,
    role TEXT,
    liked TEXT,
    confusing TEXT,
    worked_as_expected TEXT,
    feature_to_improve TEXT,
    bugs TEXT,
    rating INTEGER NOT NULL,
    suggestions TEXT,
    consent_to_publish INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC);
"""


@contextmanager
def conn():
    path = pathlib.Path(get_settings().db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(path), timeout=30.0)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=30000")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with conn() as c:
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.OperationalError:
            pass
        c.executescript(SCHEMA)
        columns = {row[1] for row in c.execute("PRAGMA table_info(investigations)")}
        if "user_id" not in columns:
            c.execute("ALTER TABLE investigations ADD COLUMN user_id TEXT REFERENCES users(id)")

    # Secure file permissions on POSIX systems
    try:
        path = pathlib.Path(get_settings().db_path).resolve()
        if os.name != "nt" and path.exists():
            path.chmod(0o600)
    except OSError:
        pass


def save(result: dict, user_id: str):
    if not user_id:
        raise ValueError("A valid user_id is required to save an investigation.")
    with conn() as c:
        f = result["file"]
        c.execute(
            "INSERT INTO investigations(id,created_at,kind,sha256,size_bytes,mime,assessment,risk,result_json,user_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (result["id"], result["created_at"], result["kind"], f["sha256"],
             f["size_bytes"], f["mime"], result["fusion"]["assessment"],
             result["fusion"]["risk_indicator"], json.dumps(result), user_id),
        )
        for m in result["modules"]:
            c.execute(
                "INSERT INTO module_results(investigation_id,module_id,status,stance,method,version,data_json) "
                "VALUES(?,?,?,?,?,?,?)",
                (result["id"], m["id"], m["status"], m["stance"], m["method"], m["version"], json.dumps(m)),
            )
        for fr in result.get("frames", []):
            c.execute(
                "INSERT INTO frame_findings(investigation_id,idx,time_s,stance,data_json) VALUES(?,?,?,?,?)",
                (result["id"], fr["index"], fr["time_s"], fr["stance"], json.dumps(fr)),
            )


def get(inv_id: str, user_id: str):
    if not user_id:
        return None
    with conn() as c:
        r = c.execute("SELECT result_json FROM investigations WHERE id=? AND user_id=?", (inv_id, user_id)).fetchone()
    return json.loads(r[0]) if r else None


def list_recent(limit: int = 20, user_id: str | None = None):
    if not user_id:
        return []
    with conn() as c:
        rows = c.execute(
            "SELECT result_json FROM investigations WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [json.loads(row[0]) for row in rows]


def delete(inv_id: str, user_id: str):
    if not user_id:
        return False
    with conn() as c:
        c.execute("UPDATE uploads SET analysis_id=NULL WHERE analysis_id=?", (inv_id,))
        return c.execute("DELETE FROM investigations WHERE id=? AND user_id=?", (inv_id, user_id)).rowcount > 0


def save_report(rep_id: str, inv_id: str, created_at: str, report: dict):
    with conn() as c:
        c.execute(
            "INSERT INTO reports(id, investigation_id, created_at, report_json) VALUES(?,?,?,?)",
            (rep_id, inv_id, created_at, json.dumps(report)),
        )


def save_feedback(data: dict, user_id: str | None = None) -> str:
    feed_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with conn() as c:
        c.execute(
            """INSERT INTO feedback(id, user_id, name, role, liked, confusing, worked_as_expected,
                                   feature_to_improve, bugs, rating, suggestions, consent_to_publish, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                feed_id,
                user_id,
                data.get("name") or None,
                data.get("role") or None,
                data.get("liked") or "",
                data.get("confusing") or "",
                data.get("worked_as_expected") or "",
                data.get("feature_to_improve") or "",
                data.get("bugs") or "",
                int(data["rating"]),
                data.get("suggestions") or "",
                1 if data.get("consent_to_publish") else 0,
                now,
            ),
        )
    return feed_id


def list_feedback(limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            """SELECT id, user_id, name, role, liked, confusing, worked_as_expected,
                      feature_to_improve, bugs, rating, suggestions, consent_to_publish, created_at
               FROM feedback ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    cols = [
        "id", "user_id", "name", "role", "liked", "confusing", "worked_as_expected",
        "feature_to_improve", "bugs", "rating", "suggestions", "consent_to_publish", "created_at",
    ]
    return [{k: (bool(v) if k == "consent_to_publish" else v) for k, v in zip(cols, row)} for row in rows]

