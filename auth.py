import os, time, datetime as dt
import streamlit as st
from streamlit_autorefresh import st_autorefresh
import extra_streamlit_components as stx

from db import fetchone, fetchall, exec_sql
from security import pbkdf2_hash_password, verify_password, make_session_token, parse_session_token

COOKIE_NAME = "content_os_session"
cookie = stx.CookieManager()

def now_utc() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def get_secret() -> str:
    s = os.environ.get("SESSION_SECRET")
    if not s and hasattr(st, "secrets"):
        s = st.secrets.get("SESSION_SECRET", "")
    return str(s or "")

def bootstrap_admin():
    admin_email = os.environ.get("ADMIN_EMAIL") or (st.secrets.get("ADMIN_EMAIL") if hasattr(st,'secrets') else None)
    admin_password = os.environ.get("ADMIN_PASSWORD") or (st.secrets.get("ADMIN_PASSWORD") if hasattr(st,'secrets') else None)
    if not admin_email or not admin_password:
        return
    admin_email = admin_email.strip().lower()
    if fetchone("SELECT * FROM users WHERE email=?", (admin_email,)):
        return
    salt, pw = pbkdf2_hash_password(admin_password)
    exec_sql("INSERT INTO users (email,name,salt,password_hash,is_admin,is_active,created_at) VALUES (?,?,?,?,?,?,?)",
             (admin_email,"Admin",salt,pw,1,1,now_utc()))
    u = fetchone("SELECT * FROM users WHERE email=?", (admin_email,))
    exec_sql("INSERT INTO workspaces (name,created_at,created_by_user_id) VALUES (?,?,?)", ("Admin Workspace", now_utc(), u["id"]))
    ws = fetchone("SELECT * FROM workspaces ORDER BY id DESC LIMIT 1")
    exec_sql("INSERT INTO workspace_members (workspace_id,user_id,role,added_at) VALUES (?,?,?,?)", (ws["id"], u["id"], "owner", now_utc()))

def set_cookie_for_user(user: dict):
    secret = get_secret()
    if not secret:
        return
    tok = make_session_token(user["id"], user["email"], secret)
    cookie.set(COOKIE_NAME, tok, max_age=60*60*24*7)

def clear_cookie():
    try: cookie.delete(COOKIE_NAME)
    except Exception: pass

def restore_user_from_cookie():
    secret = get_secret()
    if not secret:
        return None
    tok = cookie.get(COOKIE_NAME)
    if not tok:
        return None
    data = parse_session_token(tok, secret)
    if not data:
        return None
    u = fetchone("SELECT * FROM users WHERE id=?", (int(data["uid"]),))
    if u and u.get("is_active"):
        return u
    return None

def get_workspaces(user_id: int):
    return fetchall("""
        SELECT w.id, w.name, wm.role
        FROM workspace_members wm JOIN workspaces w ON w.id = wm.workspace_id
        WHERE wm.user_id=? ORDER BY w.name
    """, (user_id,))

def set_active_workspace(user: dict, workspace_id: int | None = None):
    wss = get_workspaces(user["id"])
    if not wss:
        return None
    if workspace_id is None:
        return wss[0]
    for w in wss:
        if int(w["id"]) == int(workspace_id):
            return w
    return wss[0]

def logout():
    clear_cookie()
    st.session_state["user"] = None
    st.session_state["workspace"] = None
    st.session_state["last_activity"] = time.time()
    st.rerun()

def idle_guard():
    st_autorefresh(interval=30_000, key="idle_refresh")
    now = time.time()
    last = st.session_state.get("last_activity", now)
    st.session_state["last_activity"] = now
    if st.session_state.get("user") and (now - last) > 300:
        logout()

def login_ui():
    st.title("Content OS — Login")
    tabs = st.tabs(["Entrar", "Solicitar conta", "Aceitar convite"])

    with tabs[0]:
        email = st.text_input("Email", key="li_email").strip().lower()
        pw = st.text_input("Senha", type="password", key="li_pw")
        if st.button("Entrar", type="primary"):
            u = fetchone("SELECT * FROM users WHERE email=?", (email,))
            if not u:
                st.error("Usuário não encontrado.")
            elif not u["is_active"]:
                st.error("Conta pendente ou desativada.")
            elif not verify_password(pw, u["salt"], u["password_hash"]):
                st.error("Senha inválida.")
            else:
                st.session_state["user"] = u
                st.session_state["workspace"] = set_active_workspace(u)
                set_cookie_for_user(u)
                st.rerun()

    with tabs[1]:
        st.caption("Solicitação de conta requer aprovação do Admin.")
        email = st.text_input("Email", key="su_email").strip().lower()
        name = st.text_input("Nome", key="su_name").strip()
        ws = st.text_input("Nome do painel", value="Meu Painel", key="su_ws").strip()
        p1 = st.text_input("Senha", type="password", key="su_p1")
        p2 = st.text_input("Confirmar senha", type="password", key="su_p2")
        if st.button("Solicitar"):
            if not email or not p1:
                st.error("Email e senha são obrigatórios.")
            elif p1 != p2:
                st.error("Senhas não conferem.")
            else:
                salt, ph = pbkdf2_hash_password(p1)
                exec_sql("INSERT INTO signup_requests (email,name,salt,password_hash,workspace_name,created_at,status) VALUES (?,?,?,?,?,?,?)",
                         (email,name,salt,ph,ws,now_utc(),"pending"))
                st.success("Solicitação enviada.")

    with tabs[2]:
        email = st.text_input("Seu email", key="iv_email").strip().lower()
        token = st.text_input("Token do convite", key="iv_token").strip()
        if st.button("Aceitar convite", type="primary"):
            u = fetchone("SELECT * FROM users WHERE email=?", (email,))
            inv = fetchone("SELECT * FROM invites WHERE token=?", (token,))
            if not u or not u.get("is_active"):
                st.error("Conta inexistente ou não ativa.")
                st.stop()
            if not inv:
                st.error("Convite inválido.")
                st.stop()
            # attach
            try:
                exec_sql("INSERT INTO workspace_members (workspace_id,user_id,role,added_at) VALUES (?,?,?,?)",
                         (inv["workspace_id"], u["id"], inv["role"], now_utc()))
            except Exception:
                exec_sql("UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?",
                         (inv["role"], inv["workspace_id"], u["id"]))
            exec_sql("UPDATE invites SET used_by_user_id=?, used_at=? WHERE id=?", (u["id"], now_utc(), inv["id"]))
            st.success("Convite aceito! Faça login.")
