import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = Path("storage") / "app.db"

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        profile_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS transcriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        segments_json TEXT NOT NULL DEFAULT '[]',
        engine TEXT NOT NULL DEFAULT 'whisper',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (video_id) REFERENCES videos(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS content_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
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
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_id INTEGER NOT NULL,
        weekday INTEGER NOT NULL, -- 0=Mon ... 6=Sun
        hour INTEGER NOT NULL,
        minute INTEGER NOT NULL,
        spec_json TEXT NOT NULL, -- e.g. {"ideas":3,"reels_copies":4}
        provider_default TEXT NOT NULL DEFAULT 'groq',
        model_default TEXT NOT NULL DEFAULT 'llama-3.3-70b-versatile',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (client_id) REFERENCES clients(id)
    );
    """)

    conn.commit()
    conn.close()

def row_to_dict(r) -> Dict[str, Any]:
    return dict(r) if r is not None else {}

def list_clients() -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM clients ORDER BY name ASC").fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        d["profile"]=json.loads(d.get("profile_json") or "{}")
        out.append(d)
    return out

def get_client(client_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    conn.close()
    if not r:
        return None
    d=row_to_dict(r)
    d["profile"]=json.loads(d.get("profile_json") or "{}")
    return d

def upsert_client(name: str, description: str, profile: Dict[str, Any], client_id: Optional[int]=None) -> int:
    conn=get_conn()
    cur=conn.cursor()
    profile_json=json.dumps(profile, ensure_ascii=False)
    if client_id is None:
        cur.execute(
            "INSERT INTO clients(name, description, profile_json, updated_at) VALUES(?,?,?,datetime('now'))",
            (name.strip(), description.strip(), profile_json),
        )
        cid=cur.lastrowid
    else:
        cur.execute(
            "UPDATE clients SET name=?, description=?, profile_json=?, updated_at=datetime('now') WHERE id=?",
            (name.strip(), description.strip(), profile_json, client_id),
        )
        cid=client_id
    conn.commit()
    conn.close()
    return int(cid)

def delete_client(client_id: int) -> None:
    conn=get_conn()
    cur=conn.cursor()
    # cascade manually
    cur.execute("DELETE FROM content_items WHERE client_id=?", (client_id,))
    vids=cur.execute("SELECT id FROM videos WHERE client_id=?", (client_id,)).fetchall()
    vid_ids=[int(v["id"]) for v in vids]
    if vid_ids:
        cur.execute(f"DELETE FROM transcriptions WHERE video_id IN ({','.join(['?']*len(vid_ids))})", tuple(vid_ids))
    cur.execute("DELETE FROM videos WHERE client_id=?", (client_id,))
    cur.execute("DELETE FROM schedules WHERE client_id=?", (client_id,))
    cur.execute("DELETE FROM clients WHERE id=?", (client_id,))
    conn.commit()
    conn.close()

def add_video(client_id: int, filename: str, filepath: str) -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute(
        "INSERT INTO videos(client_id, filename, filepath) VALUES(?,?,?)",
        (client_id, filename, filepath),
    )
    vid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(vid)

def list_videos(client_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute("SELECT * FROM videos WHERE client_id=? ORDER BY created_at DESC", (client_id,)).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]

def get_video(video_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    conn.close()
    return row_to_dict(r) if r else None

def add_transcription(video_id: int, text: str, segments: List[Dict[str, Any]], engine: str="whisper") -> int:
    conn=get_conn()
    cur=conn.cursor()
    cur.execute(
        "INSERT INTO transcriptions(video_id, text, segments_json, engine) VALUES(?,?,?,?)",
        (video_id, text, json.dumps(segments, ensure_ascii=False), engine),
    )
    tid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(tid)

def list_transcriptions_for_video(video_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute("SELECT * FROM transcriptions WHERE video_id=? ORDER BY created_at DESC", (video_id,)).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        d["segments"]=json.loads(d.get("segments_json") or "[]")
        out.append(d)
    return out

def get_transcription(transcription_id: int) -> Optional[Dict[str, Any]]:
    conn=get_conn()
    r=conn.execute("SELECT * FROM transcriptions WHERE id=?", (transcription_id,)).fetchone()
    conn.close()
    if not r:
        return None
    d=row_to_dict(r)
    d["segments"]=json.loads(d.get("segments_json") or "[]")
    return d

def add_content_item(
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
        (client_id, type, title, input_source, input_ref, provider, model, prompt_used, output_text, status, tags)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (client_id, type_, title, input_source, input_ref, provider, model, prompt_used, output_text, status, tags),
    )
    cid=cur.lastrowid
    conn.commit()
    conn.close()
    return int(cid)

def list_content_items(client_id: int, limit: int=200) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute(
        "SELECT * FROM content_items WHERE client_id=? ORDER BY created_at DESC LIMIT ?",
        (client_id, limit),
    ).fetchall()
    conn.close()
    return [row_to_dict(r) for r in rows]



def list_schedules(client_id: int) -> List[Dict[str, Any]]:
    conn=get_conn()
    rows=conn.execute("SELECT * FROM schedules WHERE client_id=? ORDER BY weekday, hour, minute", (client_id,)).fetchall()
    conn.close()
    out=[]
    for r in rows:
        d=row_to_dict(r)
        d["spec"]=json.loads(d.get("spec_json") or "{}")
        out.append(d)
    return out

def upsert_schedule(
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
    spec_json=json.dumps(spec, ensure_ascii=False)
    if schedule_id is None:
        cur.execute(
            "INSERT INTO schedules(client_id, weekday, hour, minute, spec_json, provider_default, model_default, enabled) VALUES(?,?,?,?,?,?,?,?)",
            (client_id, weekday, hour, minute, spec_json, provider_default, model_default, int(enabled)),
        )
        sid=cur.lastrowid
    else:
        cur.execute(
            "UPDATE schedules SET weekday=?, hour=?, minute=?, spec_json=?, provider_default=?, model_default=?, enabled=? WHERE id=? AND client_id=?",
            (weekday, hour, minute, spec_json, provider_default, model_default, int(enabled), schedule_id, client_id),
        )
        sid=schedule_id
    conn.commit()
    conn.close()
    return int(sid)

def delete_schedule(schedule_id: int, client_id: int) -> None:
    conn=get_conn()
    conn.execute("DELETE FROM schedules WHERE id=? AND client_id=?", (schedule_id, client_id))
    conn.commit()
    conn.close()
