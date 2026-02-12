import os
import sqlite3
import datetime as dt
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("CONTENT_OS_DB", "content_os.db")

def now_utc() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def exec_sql(sql: str, params: tuple = ()) -> None:
    with db() as conn:
        conn.execute(sql, params)
        conn.commit()

def fetchone(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    with db() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

def fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with db() as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def init_db() -> None:
    exec_sql("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS signup_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        name TEXT,
        salt TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        workspace_name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        reviewed_at TEXT
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL,
        created_by_user_id INTEGER
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS workspace_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        added_at TEXT NOT NULL,
        UNIQUE(workspace_id, user_id)
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        workspace_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        email_restriction TEXT,
        created_by_user_id INTEGER,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used_by_user_id INTEGER,
        used_at TEXT
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        system_prompt TEXT,
        brand_voice TEXT,
        audience TEXT,
        offer TEXT,
        differentiators TEXT,
        objections TEXT,
        constraints TEXT,
        cta TEXT,
        templates_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS transcriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        video_id INTEGER NOT NULL,
        engine TEXT NOT NULL,
        language TEXT,
        whisper_model TEXT,
        text TEXT NOT NULL,
        segments_json TEXT,
        created_at TEXT NOT NULL
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS content_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        client_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        title TEXT,
        input_source TEXT NOT NULL,
        input_ref TEXT,
        provider TEXT NOT NULL,
        model TEXT NOT NULL,
        prompt_used TEXT NOT NULL,
        output_text TEXT NOT NULL,
        tags TEXT,
        status TEXT NOT NULL DEFAULT 'draft',
        created_by_user_id INTEGER,
        created_at TEXT NOT NULL
    )
    """)
    exec_sql("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER,
        actor_user_id INTEGER,
        action TEXT NOT NULL,
        details_json TEXT,
        created_at TEXT NOT NULL
    )
    """)
