import os
import sqlite3
from typing import Optional, List

def _get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        try:
            import streamlit as st
            url = str(st.secrets.get("DATABASE_URL", "")).strip()
        except Exception:
            url = ""
    return url

DATABASE_URL = _get_database_url()
DB_PATH = os.environ.get("CONTENT_OS_DB", "content_os.db")

_IS_PG = bool(DATABASE_URL)

if _IS_PG:
    import psycopg
    from psycopg.rows import dict_row


def _adapt_sql(sql: str) -> str:
    # Converte placeholders do SQLite (?) para Postgres (%s)
    return sql.replace("?", "%s") if _IS_PG else sql


def db():
    """Retorna uma conexão válida (Postgres se DATABASE_URL existir, senão SQLite)."""
    if _IS_PG:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def exec_sql(sql: str, params: tuple = ()) -> None:
    sql = _adapt_sql(sql)
    if _IS_PG:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
        return

    with db() as conn:
        conn.execute(sql, params)
        conn.commit()


def fetchone(sql: str, params: tuple = ()) -> Optional[dict]:
    sql = _adapt_sql(sql)
    if _IS_PG:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return dict(row) if row else None

    with db() as conn:
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None


def fetchall(sql: str, params: tuple = ()) -> List[dict]:
    sql = _adapt_sql(sql)
    if _IS_PG:
        with db() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]

    with db() as conn:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]


def init_db():
    if _IS_PG:
        # Postgres schema
        exec_sql("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
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
            id BIGSERIAL PRIMARY KEY,
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
            id BIGSERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by_user_id BIGINT
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            role TEXT NOT NULL,
            added_at TEXT NOT NULL,
            UNIQUE(workspace_id, user_id)
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS invites (
            id BIGSERIAL PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            workspace_id BIGINT NOT NULL,
            role TEXT NOT NULL,
            email_restriction TEXT,
            created_by_user_id BIGINT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_by_user_id BIGINT,
            used_at TEXT
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS clients (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            system_prompt TEXT,
            templates_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS videos (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT NOT NULL,
            client_id BIGINT NOT NULL,
            filename TEXT NOT NULL,
            filepath TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS transcriptions (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT NOT NULL,
            video_id BIGINT NOT NULL,
            whisper_model TEXT,
            language TEXT,
            text TEXT NOT NULL,
            segments_json TEXT,
            created_at TEXT NOT NULL
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS content_items (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT NOT NULL,
            client_id BIGINT NOT NULL,
            type TEXT NOT NULL,
            title TEXT,
            input_source TEXT NOT NULL,
            input_ref TEXT,
            model TEXT NOT NULL,
            prompt_used TEXT NOT NULL,
            output_text TEXT NOT NULL,
            tags TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            created_by_user_id BIGINT,
            created_at TEXT NOT NULL
        )
        """)

        exec_sql("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            workspace_id BIGINT,
            actor_user_id BIGINT,
            action TEXT NOT NULL,
            details_json TEXT,
            created_at TEXT NOT NULL
        )
        """)
        return

    # SQLite schema
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
        whisper_model TEXT,
        language TEXT,
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
