
import base64
import os
import hashlib
import hmac
import secrets
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path("storage") / "app.db"

# ----------------- connection -----------------
def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    r = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(r)

def _col_exists(conn: sqlite3.Connection, table: str, col: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == col for r in rows)

# ----------------- auth utils -----------------
_PBKDF2_ITERATIONS = 210_000

def _hash_password(password: str) -> str:
    salt = hashlib.sha256(str(Path(DB_PATH).absolute()).encode("utf-8")).digest()[:8]  # stable but not secret
    salt = salt + hashlib.sha256(os.urandom(16)).digest()[:8]  # per-user random
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32)
    blob = salt + dk
    return base64.b64encode(blob).decode("utf-8")

def _verify_password(password: str, stored: str) -> bool:
    try:
        blob = base64.b64decode(stored.encode("utf-8"))
        salt, dk = blob[:16], blob[16:]
        cand = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS, dklen=32)
        return hmac.compare_digest(cand, dk)
    except Exception:
        return False

# ----------------- schema -----------------
def init_db() -> None:
    """
    Initializes DB and runs a one-time migration from the legacy single-tenant schema
    (clients/videos/transcriptions/content_items/schedules) to multi-tenant schema with:
      users, workspaces, memberships, invites + workspace_id columns.
    """
    conn = get_conn()
    cur = conn.cursor()

    legacy = _table_exists(conn, "clients") and not _table_exists(conn, "workspaces")

    if legacy:
        _migrate_legacy_to_multitenant(conn)

    # Core tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 0,
    approved_at TEXT,
    requested_workspace_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
    """)

    # Ensure new auth columns exist (for older DBs)
    for col_def in [
        ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("is_active", "INTEGER NOT NULL DEFAULT 0"),
        ("approved_at", "TEXT"),
        ("requested_workspace_name", "TEXT NOT NULL DEFAULT ''"),
    ]:
        col, sql = col_def
        if not _col_exists(conn, "users", col):
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {sql};")


    cur.execute("""
    CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS memberships (
        user_id INTEGER NOT NULL,
        workspace_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'editor', -- owner | editor | viewer
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, workspace_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        invited_email TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL DEFAULT 'editor',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT,
        used_at TEXT,
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );
    """)


    # Ensure invites has expires_at (for older DBs)
    if _table_exists(conn, "invites") and not _col_exists(conn, "invites", "expires_at"):
        cur.execute("ALTER TABLE invites ADD COLUMN expires_at TEXT;")


    # Password reset tokens (admin-generated or requested)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS password_resets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL,
        used_at TEXT,
        created_by_admin INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    # Audit log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_user_id INTEGER,
        workspace_id INTEGER,
        action TEXT NOT NULL,
        entity_type TEXT NOT NULL DEFAULT '',
        entity_id INTEGER,
        meta_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (actor_user_id) REFERENCES users(id),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );
    """)

    # Tenant tables
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        profile_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(workspace_id, name),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transcriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        video_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        segments_json TEXT NOT NULL DEFAULT '[]',
        engine TEXT NOT NULL DEFAULT 'whisper',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
        FOREIGN KEY (video_id) REFERENCES videos(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS content_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        input_source TEXT NOT NULL DEFAULT 'manual', -- manual | transcription
        input_ref INTEGER, -- transcription_id
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_used TEXT NOT NULL,
        output_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', -- draft | approved | published
        tags TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        weekday INTEGER NOT NULL, -- 0=Mon ... 6=Sun
        hour INTEGER NOT NULL,
        minute INTEGER NOT NULL,
        spec_json TEXT NOT NULL,
        provider_default TEXT NOT NULL DEFAULT 'groq',
        model_default TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    conn.commit()
    conn.close()

def _migrate_legacy_to_multitenant(conn: sqlite3.Connection) -> None:
    """
    Legacy had: clients(name UNIQUE), videos(client_id), transcriptions(video_id), content_items(client_id), schedules(client_id)
    We create new tables with workspace_id, copy into workspace_id=1, then swap.
    """
    cur = conn.cursor()

    # Create default workspace
    cur.execute("CREATE TABLE IF NOT EXISTS workspaces (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));")
    cur.execute("INSERT INTO workspaces (id, name) VALUES (1, 'Workspace Padrão') ON CONFLICT(id) DO NOTHING;")

    # clients_new
    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        profile_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(workspace_id, name)
    );
    """)
    if _table_exists(conn, "clients"):
        rows = conn.execute("SELECT id, name, description, profile_json, created_at, updated_at FROM clients").fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO clients_new (id, workspace_id, name, description, profile_json, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (r["id"], 1, r["name"], r["description"], r["profile_json"], r["created_at"], r["updated_at"]),
            )

    # videos_new
    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    if _table_exists(conn, "videos"):
        rows = conn.execute("SELECT id, client_id, filename, filepath, created_at FROM videos").fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO videos_new (id, workspace_id, client_id, filename, filepath, created_at) VALUES (?,?,?,?,?,?)",
                (r["id"], 1, r["client_id"], r["filename"], r["filepath"], r["created_at"]),
            )

    # transcriptions_new
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transcriptions_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        video_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        segments_json TEXT NOT NULL DEFAULT '[]',
        engine TEXT NOT NULL DEFAULT 'whisper',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    if _table_exists(conn, "transcriptions"):
        rows = conn.execute("SELECT id, video_id, text, segments_json, engine, created_at FROM transcriptions").fetchall()
        for r in rows:
            cur.execute(
                "INSERT INTO transcriptions_new (id, workspace_id, video_id, text, segments_json, engine, created_at) VALUES (?,?,?,?,?,?,?)",
                (r["id"], 1, r["video_id"], r["text"], r["segments_json"], r["engine"], r["created_at"]),
            )

    # content_items_new
    cur.execute("""
    CREATE TABLE IF NOT EXISTS content_items_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        input_source TEXT NOT NULL DEFAULT 'manual',
        input_ref INTEGER,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_used TEXT NOT NULL,
        output_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft',
        tags TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    if _table_exists(conn, "content_items"):
        rows = conn.execute("SELECT * FROM content_items").fetchall()
        for r in rows:
            cur.execute(
                """INSERT INTO content_items_new
                (id, workspace_id, client_id, type, title, input_source, input_ref, provider, model, prompt_used, output_text, status, tags, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], 1, r["client_id"], r["type"], r["title"], r["input_source"], r["input_ref"], r["provider"], r["model"], r["prompt_used"], r["output_text"], r["status"], r["tags"], r["created_at"]),
            )

    # schedules_new
    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        weekday INTEGER NOT NULL,
        hour INTEGER NOT NULL,
        minute INTEGER NOT NULL,
        spec_json TEXT NOT NULL,
        provider_default TEXT NOT NULL DEFAULT 'groq',
        model_default TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    if _table_exists(conn, "schedules"):
        rows = conn.execute("SELECT * FROM schedules").fetchall()
        for r in rows:
            cur.execute(
                """INSERT INTO schedules_new
                (id, workspace_id, client_id, weekday, hour, minute, spec_json, provider_default, model_default, enabled, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r["id"], 1, r["client_id"], r["weekday"], r["hour"], r["minute"], r["spec_json"], r["provider_default"], r["model_default"], r["enabled"], r["created_at"]),
            )

    # Swap
    for t in ["clients","videos","transcriptions","content_items","schedules"]:
        if _table_exists(conn, t):
            cur.execute(f"DROP TABLE {t};")
    cur.execute("ALTER TABLE clients_new RENAME TO clients;")
    cur.execute("ALTER TABLE videos_new RENAME TO videos;")
    cur.execute("ALTER TABLE transcriptions_new RENAME TO transcriptions;")
    cur.execute("ALTER TABLE content_items_new RENAME TO content_items;")
    cur.execute("ALTER TABLE schedules_new RENAME TO schedules;")

    conn.commit()

# ----------------- helpers -----------------
def row_to_dict(r) -> Dict[str, Any]:
    return dict(r) if r is not None else {}

# ----------------- auth: users/workspaces -----------------

def create_user(email: str, password: str, name: str = "", *, is_admin: bool = False, is_active: bool = False, requested_workspace_name: str = "") -> int:
    """Create a user. For normal signups use is_active=False and store requested_workspace_name."""
    conn = get_conn()
    cur = conn.cursor()
    ph = _hash_password(password)
    cur.execute(
        "INSERT INTO users (email, name, password_hash, is_admin, is_active, requested_workspace_name) VALUES (?,?,?,?,?,?)",
        (email.lower().strip(), name.strip(), ph, 1 if is_admin else 0, 1 if is_active else 0, (requested_workspace_name or "").strip()),
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    return int(uid)

def count_admins() -> int:
    conn = get_conn()
    r = conn.execute("SELECT COUNT(1) AS n FROM users WHERE is_admin=1").fetchone()
    conn.close()
    return int(r["n"]) if r else 0

def bootstrap_admin_from_env() -> Optional[int]:
    """Create an initial admin user if none exists. Uses ADMIN_EMAIL/ADMIN_PASSWORD env vars."""
    if count_admins() > 0:
        return None
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email or not password:
        return None
    conn = get_conn()
    r = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if r:
        conn.execute("UPDATE users SET is_admin=1, is_active=1, approved_at=datetime('now') WHERE email=?", (email,))
        conn.commit()
        conn.close()
        return int(r["id"])
    conn.close()
    return create_user(email=email, password=password, name="Admin", is_admin=True, is_active=True)

def verify_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    r = conn.execute("SELECT * FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    conn.close()
    if not r:
        return None
    d = row_to_dict(r)
    if _verify_password(password, d.get("password_hash","")):
        d.pop("password_hash", None)
        return d
    return None

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT id, email, name, created_at FROM users WHERE email=?", (email.lower().strip(),)).fetchone()
    conn.close()
    return row_to_dict(r) if r else None


def list_pending_users() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, email, name, requested_workspace_name, created_at FROM users WHERE is_active=0 ORDER BY created_at ASC"
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def set_user_active(user_id: int, active: bool) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE users SET is_active=?, approved_at=CASE WHEN ?=1 THEN datetime('now') ELSE approved_at END WHERE id=?",
        (1 if active else 0, 1 if active else 0, user_id),
    )
    conn.commit()
    conn.close()

def promote_to_admin(user_id: int, is_admin: bool) -> None:
    conn = get_conn()
    conn.execute("UPDATE users SET is_admin=? WHERE id=?", (1 if is_admin else 0, user_id))
    conn.commit()
    conn.close()

def approve_user(user_id: int) -> Optional[int]:
    """Activate user and create their requested workspace, returning workspace_id."""
    conn = get_conn()
    cur = conn.cursor()
    u = cur.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        conn.close()
        return None
    cur.execute("UPDATE users SET is_active=1, approved_at=datetime('now') WHERE id=?", (user_id,))
    ws_name = (u["requested_workspace_name"] or "").strip() or "Meu Painel"
    cur.execute("INSERT INTO workspaces (name) VALUES (?)", (ws_name,))
    wid = cur.lastrowid
    cur.execute("INSERT OR REPLACE INTO memberships (user_id, workspace_id, role) VALUES (?,?,?)", (user_id, wid, "owner"))
    conn.commit()
    conn.close()
    return int(wid)

def delete_user(user_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM memberships WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

def list_users() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, email, name, is_admin, is_active, approved_at, created_at FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]


def create_workspace(name: str) -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute("INSERT INTO workspaces (name) VALUES (?)", (name.strip(),))
    wid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(wid)

def add_membership(user_id: int, workspace_id: int, role: str = "member") -> None:
    conn=get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO memberships (user_id, workspace_id, role) VALUES (?,?,?)",
        (user_id, workspace_id, role),
    )
    conn.commit()
    conn.close()

def list_user_workspaces(user_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute(
        """SELECT w.id, w.name, m.role, w.created_at
           FROM workspaces w
           JOIN memberships m ON m.workspace_id=w.id
           WHERE m.user_id=?
           ORDER BY w.created_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def get_membership(user_id: int, workspace_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM memberships WHERE user_id=? AND workspace_id=?", (user_id, workspace_id)).fetchone()
    conn.close()
    return row_to_dict(r) if r else None

def create_invite(workspace_id: int, invited_email: str = "", role: str = "editor", expires_in_days: int = 7) -> str:
    """Creates an invite token for a workspace. Optionally restrict to an email and set expiry."""
    conn = get_conn()
    token = secrets.token_urlsafe(16)
    invited_email = invited_email.lower().strip()
    role = (role or "editor").strip().lower()
    if role not in ("owner","editor","viewer"):
        role = "editor"
    # expires_at stored as SQLite datetime string
    conn.execute(
        "INSERT INTO invites (workspace_id, token, invited_email, role, expires_at) VALUES (?,?,?,?,datetime('now', ?))",
        (workspace_id, token, invited_email, role, f'+{int(expires_in_days)} days'),
    )
    conn.commit()
    conn.close()
    return token

def accept_invite(token: str, user_id: int) -> Optional[int]:
    """Accepts an invite if valid, unused and not expired. Returns workspace_id or None."""
    conn = get_conn()
    cur = conn.cursor()
    inv = cur.execute(
        """SELECT * FROM invites
            WHERE token=? AND used_at IS NULL
              AND (expires_at IS NULL OR expires_at > datetime('now'))""",
        (token.strip(),),
    ).fetchone()
    if not inv:
        conn.close()
        return None

    # If invite is restricted to an email, enforce it
    if (inv["invited_email"] or "").strip():
        u = cur.execute("SELECT email FROM users WHERE id=?", (user_id,)).fetchone()
        if not u or u["email"].lower().strip() != inv["invited_email"].lower().strip():
            conn.close()
            return None

    workspace_id = int(inv["workspace_id"])
    role = (inv["role"] or "editor").strip().lower()
    if role not in ("owner","editor","viewer"):
        role = "editor"

    cur.execute("UPDATE invites SET used_at=datetime('now') WHERE id=?", (inv["id"],))
    cur.execute(
        "INSERT OR REPLACE INTO memberships (user_id, workspace_id, role) VALUES (?,?,?)",
        (user_id, workspace_id, role),
    )
    conn.commit()
    conn.close()
    return workspace_id

def list_clients(workspace_id: int) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM clients WHERE workspace_id=? ORDER BY name ASC", (workspace_id,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["profile"] = json.loads(d.get("profile_json") or "{}")
        out.append(d)
    return out

def get_client(workspace_id: int, client_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id)).fetchone()
    conn.close()
    if not r:
        return None
    d=row_to_dict(r)
    d["profile"]=json.loads(d.get("profile_json") or "{}")
    return d

def upsert_client(name: str, description: str, profile: Dict[str, Any], workspace_id: int, client_id: Optional[int]=None) -> int:
    conn=get_conn()
    cur=conn.cursor()
    if client_id:
        cur.execute(
            "UPDATE clients SET name=?, description=?, profile_json=?, updated_at=datetime('now') WHERE workspace_id=? AND id=?",
            (name.strip(), description or "", json.dumps(profile or {}, ensure_ascii=False), workspace_id, client_id),
        )
        cid = client_id
    else:
        cur.execute(
            "INSERT INTO clients (workspace_id, name, description, profile_json) VALUES (?,?,?,?)",
            (workspace_id, name.strip(), description or "", json.dumps(profile or {}, ensure_ascii=False)),
        )
        cid = cur.lastrowid
    conn.commit()
    conn.close()
    return int(cid)

def delete_client(workspace_id: int, client_id: int) -> None:
    conn=get_conn()
    conn.execute("DELETE FROM content_items WHERE workspace_id=? AND client_id=?", (workspace_id, client_id))
    conn.execute("DELETE FROM schedules WHERE workspace_id=? AND client_id=?", (workspace_id, client_id))
    vids = conn.execute("SELECT id FROM videos WHERE workspace_id=? AND client_id=?", (workspace_id, client_id)).fetchall()
    for v in vids:
        conn.execute("DELETE FROM transcriptions WHERE workspace_id=? AND video_id=?", (workspace_id, v["id"]))
    conn.execute("DELETE FROM videos WHERE workspace_id=? AND client_id=?", (workspace_id, client_id))
    conn.execute("DELETE FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id))
    conn.commit()
    conn.close()

# ----------------- videos & transcriptions -----------------
def add_video(workspace_id: int, client_id: int, filename: str, filepath: str) -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute("INSERT INTO videos (workspace_id, client_id, filename, filepath) VALUES (?,?,?,?)", (workspace_id, client_id, filename, filepath))
    vid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(vid)

def list_videos(workspace_id: int, client_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute("SELECT * FROM videos WHERE workspace_id=? AND client_id=? ORDER BY created_at DESC", (workspace_id, client_id)).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def get_video(workspace_id: int, video_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM videos WHERE workspace_id=? AND id=?", (workspace_id, video_id)).fetchone()
    conn.close()
    return row_to_dict(r) if r else None

def add_transcription(workspace_id: int, video_id: int, text: str, segments: List[Dict[str, Any]], engine: str="whisper") -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute(
        "INSERT INTO transcriptions (workspace_id, video_id, text, segments_json, engine) VALUES (?,?,?,?,?)",
        (workspace_id, video_id, text or "", json.dumps(segments or [], ensure_ascii=False), engine),
    )
    tid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(tid)

def list_transcriptions_for_video(workspace_id: int, video_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute("SELECT * FROM transcriptions WHERE workspace_id=? AND video_id=? ORDER BY created_at DESC", (workspace_id, video_id)).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        d["segments"]=json.loads(d.get("segments_json") or "[]")
        out.append(d)
    return out

def get_transcription(workspace_id: int, transcription_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM transcriptions WHERE workspace_id=? AND id=?", (workspace_id, transcription_id)).fetchone()
    conn.close()
    if not r:
        return None
    d=row_to_dict(r)
    d["segments"]=json.loads(d.get("segments_json") or "[]")
    return d

# ----------------- content -----------------
def add_content_item(
    workspace_id: int,
    client_id: int,
    type_: str,
    title: str,
    input_source: str,
    input_ref: Optional[int],
    provider: str,
    model: str,
    prompt_used: str,
    output_text: str,
    status: str="draft",
    tags: str="",
) -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute(
        """INSERT INTO content_items
        (workspace_id, client_id, type, title, input_source, input_ref, provider, model, prompt_used, output_text, status, tags)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (workspace_id, client_id, type_, title or "", input_source, input_ref, provider, model, prompt_used, output_text, status, tags or ""),
    )
    cid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(cid)

def list_content_items(workspace_id: int, client_id: int, limit: int=200) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute(
        "SELECT * FROM content_items WHERE workspace_id=? AND client_id=? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, client_id, limit),
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def list_content_items_by_video(workspace_id: int, client_id: int, video_id: int, limit: int=200) -> List[Dict[str, Any]]:
    tag = f"video:{video_id}"
    conn=get_conn()
    rows=conn.execute(
        "SELECT * FROM content_items WHERE workspace_id=? AND client_id=? AND tags LIKE ? ORDER BY created_at DESC LIMIT ?",
        (workspace_id, client_id, f"%{tag}%", limit),
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

# ----------------- schedules -----------------
def list_schedules(workspace_id: int, client_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute(
        "SELECT * FROM schedules WHERE workspace_id=? AND client_id=? ORDER BY weekday, hour, minute",
        (workspace_id, client_id),
    ).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        d["spec"]=json.loads(d.get("spec_json") or "{}")
        out.append(d)
    return out

def upsert_schedule(
    workspace_id: int,
    client_id: int,
    weekday: int,
    hour: int,
    minute: int,
    spec: Dict[str, Any],
    provider_default: str="groq",
    model_default: str="llama-3.3-70b-versatile",
    enabled: int=1,
    schedule_id: Optional[int]=None,
) -> int:
    conn=get_conn()
    cur=conn.cursor()
    if schedule_id:
        cur.execute(
            """UPDATE schedules SET weekday=?, hour=?, minute=?, spec_json=?, provider_default=?, model_default=?, enabled=?
               WHERE workspace_id=? AND id=?""",
            (weekday, hour, minute, json.dumps(spec or {}, ensure_ascii=False), provider_default, model_default, int(enabled), workspace_id, schedule_id),
        )
        sid=schedule_id
    else:
        cur.execute(
            """INSERT INTO schedules (workspace_id, client_id, weekday, hour, minute, spec_json, provider_default, model_default, enabled)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (workspace_id, client_id, weekday, hour, minute, json.dumps(spec or {}, ensure_ascii=False), provider_default, model_default, int(enabled)),
        )
        sid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(sid)

def delete_schedule(workspace_id: int, schedule_id: int) -> None:
    conn=get_conn()
    conn.execute("DELETE FROM schedules WHERE workspace_id=? AND id=?", (workspace_id, schedule_id))
    conn.commit()
    conn.close()


# ----------------- password reset -----------------
def create_password_reset_for_user(user_id: int, expires_minutes: int = 60, created_by_admin: int = 0) -> str:
    conn = get_conn()
    token = secrets.token_urlsafe(24)
    conn.execute(
        "INSERT INTO password_resets (user_id, token, expires_at, created_by_admin) VALUES (?,?,datetime('now', ?),?)",
        (user_id, token, f'+{int(expires_minutes)} minutes', int(created_by_admin)),
    )
    conn.commit()
    conn.close()
    return token

def list_password_resets(active_only: bool = True) -> List[Dict[str, Any]]:
    conn = get_conn()
    if active_only:
        rows = conn.execute(
            "SELECT pr.*, u.email FROM password_resets pr JOIN users u ON u.id=pr.user_id "
            "WHERE pr.used_at IS NULL AND pr.expires_at > datetime('now') ORDER BY pr.created_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT pr.*, u.email FROM password_resets pr JOIN users u ON u.id=pr.user_id "
            "ORDER BY pr.created_at DESC"
        ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def reset_password_with_token(token: str, new_password: str) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    pr = cur.execute(
        "SELECT * FROM password_resets WHERE token=? AND used_at IS NULL AND expires_at > datetime('now')",
        (token.strip(),),
    ).fetchone()
    if not pr:
        conn.close()
        return False
    user_id = int(pr["user_id"])
    cur.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash_password(new_password), user_id))
    cur.execute("UPDATE password_resets SET used_at=datetime('now') WHERE id=?", (pr["id"],))
    conn.commit()
    conn.close()
    return True

# ----------------- audit log -----------------
def log_event(actor_user_id: Optional[int], workspace_id: Optional[int], action: str,
              entity_type: str = "", entity_id: Optional[int] = None, meta: Optional[Dict[str, Any]] = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (actor_user_id, workspace_id, action, entity_type, entity_id, meta_json) VALUES (?,?,?,?,?,?)",
        (
            actor_user_id if actor_user_id is not None else None,
            workspace_id if workspace_id is not None else None,
            action,
            entity_type or "",
            entity_id if entity_id is not None else None,
            json.dumps(meta or {}, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()

def list_audit(workspace_id: Optional[int] = None, limit: int = 200) -> List[Dict[str, Any]]:
    conn = get_conn()
    if workspace_id is None:
        rows = conn.execute(
            "SELECT a.*, u.email as actor_email FROM audit_log a LEFT JOIN users u ON u.id=a.actor_user_id "
            "ORDER BY a.created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT a.*, u.email as actor_email FROM audit_log a LEFT JOIN users u ON u.id=a.actor_user_id "
            "WHERE a.workspace_id=? ORDER BY a.created_at DESC LIMIT ?",
            (int(workspace_id), int(limit)),
        ).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        try:
            d["meta"]=json.loads(d.get("meta_json","{}") or "{}")
        except Exception:
            d["meta"]={}
        out.append(d)
    return out

# ----------------- membership management -----------------
def list_workspace_members(workspace_id: int) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT m.user_id, m.workspace_id, m.role, m.created_at, u.email, u.name, u.is_active "
        "FROM memberships m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=? ORDER BY u.email",
        (workspace_id,),
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def set_membership_role(workspace_id: int, user_id: int, role: str) -> None:
    role = (role or "viewer").strip().lower()
    if role not in ("owner","editor","viewer"):
        role = "viewer"
    conn = get_conn()
    conn.execute("UPDATE memberships SET role=? WHERE workspace_id=? AND user_id=?", (role, workspace_id, user_id))
    conn.commit()
    conn.close()

def remove_membership(workspace_id: int, user_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM memberships WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    conn.commit()
    conn.close()
