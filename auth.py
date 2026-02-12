import os, json, time, hmac, hashlib, base64
import streamlit as st
import extra_streamlit_components as stx
from streamlit_autorefresh import st_autorefresh

from db import fetchone, fetchall, exec_sql, now_utc

COOKIE_NAME = "content_os_session"
ROLE_ORDER = {"viewer": 0, "editor": 1, "owner": 2}

def init_session_state():
    defaults = {
        "user": None,
        "workspace_id": None,
        "workspace_name": None,
        "workspace_role": None,
        "last_activity": time.time(),
    }
    for k,v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def _get_secret() -> str:
    secret = os.environ.get("SESSION_SECRET")
    if not secret and hasattr(st, "secrets"):
        secret = st.secrets.get("SESSION_SECRET", None)
    return str(secret or "")

def _sign(payload: str) -> str:
    secret = _get_secret()
    if not secret:
        return ""
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")

def _make_token(uid: int, email: str, ttl_seconds: int = 60*60*24*7) -> str:
    exp = int(time.time()) + int(ttl_seconds)
    data = {"uid": int(uid), "email": str(email), "exp": exp}
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{payload}.{_sign(payload)}"

def _parse_token(token: str):
    try:
        payload, sig = token.split(".", 1)
        if not payload or not sig:
            return None
        if _sign(payload) != sig:
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "===").decode())
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except Exception:
        return None

def cookie_manager():
    return stx.CookieManager()

def set_cookie(user: dict):
    secret = _get_secret()
    if not secret:
        return
    cm = cookie_manager()
    cm.set(COOKIE_NAME, _make_token(user["id"], user["email"]), max_age=60*60*24*7)

def clear_cookie():
    cm = cookie_manager()
    try:
        cm.delete(COOKIE_NAME)
    except Exception:
        pass

def hash_password(password: str, salt: str = None):
    import secrets
    if salt is None:
        salt = base64.urlsafe_b64encode(os.urandom(18)).decode().rstrip("=")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return salt, base64.urlsafe_b64encode(dk).decode().rstrip("=")

def verify_password(password: str, salt: str, hashed: str) -> bool:
    _, h2 = hash_password(password, salt=salt)
    return hmac.compare_digest(h2, hashed)

def audit(action: str, details: dict | None = None, workspace_id: int | None = None, actor_user_id: int | None = None):
    if actor_user_id is None and st.session_state.get("user"):
        actor_user_id = st.session_state["user"]["id"]
    if workspace_id is None:
        workspace_id = st.session_state.get("workspace_id")
    exec_sql(
        "INSERT INTO audit_log (workspace_id, actor_user_id, action, details_json, created_at) VALUES (?,?,?,?,?)",
        (workspace_id, actor_user_id, action, json.dumps(details or {}, ensure_ascii=False), now_utc()),
    )

def bootstrap_admin():
    admin_email = os.environ.get("ADMIN_EMAIL") or (st.secrets.get("ADMIN_EMAIL") if hasattr(st, "secrets") else None)
    admin_password = os.environ.get("ADMIN_PASSWORD") or (st.secrets.get("ADMIN_PASSWORD") if hasattr(st, "secrets") else None)
    if not admin_email or not admin_password:
        return
    admin_email = admin_email.strip().lower()
    existing = fetchone("SELECT * FROM users WHERE email=?", (admin_email,))
    if existing:
        return
    salt, pw_hash = hash_password(admin_password)
    exec_sql(
        "INSERT INTO users (email, name, salt, password_hash, is_admin, is_active, created_at) VALUES (?,?,?,?,?,?,?)",
        (admin_email, "Admin", salt, pw_hash, 1, 1, now_utc()),
    )
    admin = fetchone("SELECT * FROM users WHERE email=?", (admin_email,))
    exec_sql("INSERT INTO workspaces (name, created_at, created_by_user_id) VALUES (?,?,?)",
             ("Admin Workspace", now_utc(), admin["id"]))
    ws = fetchone("SELECT * FROM workspaces ORDER BY id DESC LIMIT 1")
    exec_sql("INSERT INTO workspace_members (workspace_id, user_id, role, added_at) VALUES (?,?,?,?)",
             (ws["id"], admin["id"], "owner", now_utc()))
    audit("admin_bootstrapped", {"email": admin_email}, workspace_id=ws["id"], actor_user_id=admin["id"])

def get_user_workspaces(user_id: int):
    return fetchall("""
        SELECT w.id, w.name, wm.role
        FROM workspace_members wm
        JOIN workspaces w ON w.id = wm.workspace_id
        WHERE wm.user_id=?
        ORDER BY w.name COLLATE NOCASE
    """, (user_id,))

def set_active_workspace(user_id: int, workspace_id: int):
    ws = fetchone("SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    if not ws:
        return
    wm = fetchone("SELECT * FROM workspace_members WHERE workspace_id=? AND user_id=?", (workspace_id, user_id))
    if not wm:
        return
    st.session_state["workspace_id"] = ws["id"]
    st.session_state["workspace_name"] = ws["name"]
    st.session_state["workspace_role"] = wm["role"]

def restore_from_cookie():
    if st.session_state.get("user"):
        return
    cm = cookie_manager()
    tok = cm.get(COOKIE_NAME)
    if not tok:
        return
    data = _parse_token(tok)
    if not data:
        return
    u = fetchone("SELECT * FROM users WHERE id=?", (int(data["uid"]),))
    if not u or not u.get("is_active"):
        return
    st.session_state["user"] = u
    wss = get_user_workspaces(u["id"])
    if wss:
        set_active_workspace(u["id"], wss[0]["id"])
    audit("session_restored", {"email": u["email"]}, workspace_id=st.session_state.get("workspace_id"), actor_user_id=u["id"])

def logout():
    audit("logout", {})
    clear_cookie()
    st.session_state["user"] = None
    st.session_state["workspace_id"] = None
    st.session_state["workspace_name"] = None
    st.session_state["workspace_role"] = None
    st.rerun()

def ensure_idle_timeout(seconds: int = 300):
    # auto refresh every 30s to detect idle without user actions
    st_autorefresh(interval=30_000, key="idle_refresh")
    now = time.time()
    last = st.session_state.get("last_activity", now)
    # update on each rerun
    st.session_state["last_activity"] = now
    if st.session_state.get("user") and (now - last) > seconds:
        logout()

def require_role(min_role: str):
    role = st.session_state.get("workspace_role") or "viewer"
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(min_role, 0)

def login_ui():
    st.title("Content OS")
    st.caption("Login • Solicitar conta • Aceitar convite")
    tabs = st.tabs(["Entrar", "Solicitar conta", "Aceitar convite"])
    with tabs[0]:
        c1, c2 = st.columns(2)
        with c1:
            email = st.text_input("Email", key="login_email").strip().lower()
        with c2:
            password = st.text_input("Senha", type="password", key="login_pw")
        if st.button("Entrar", type="primary"):
            u = fetchone("SELECT * FROM users WHERE email=?", (email,))
            if not u:
                st.error("Usuário não encontrado.")
                return
            if not u["is_active"]:
                st.error("Conta pendente de aprovação ou desativada.")
                return
            if not verify_password(password, u["salt"], u["password_hash"]):
                st.error("Senha incorreta.")
                return
            st.session_state["user"] = u
            wss = get_user_workspaces(u["id"])
            if wss:
                set_active_workspace(u["id"], wss[0]["id"])
            set_cookie(u)
            audit("login", {"email": u["email"]}, workspace_id=st.session_state.get("workspace_id"), actor_user_id=u["id"])
            st.success("Logado.")
            st.rerun()

    with tabs[1]:
        st.subheader("Solicitar criação de conta (Admin aprova)")
        email = st.text_input("Email", key="su_email").strip().lower()
        name = st.text_input("Nome", key="su_name").strip()
        ws_name = st.text_input("Nome do painel", value="Meu Painel", key="su_ws").strip()
        pw1 = st.text_input("Senha", type="password", key="su_pw1")
        pw2 = st.text_input("Confirmar senha", type="password", key="su_pw2")
        if st.button("Solicitar", key="su_btn"):
            if "@" not in email:
                st.error("Email inválido.")
                return
            if len(pw1) < 8:
                st.error("Senha precisa ter 8+ caracteres.")
                return
            if pw1 != pw2:
                st.error("Senhas não conferem.")
                return
            if fetchone("SELECT * FROM users WHERE email=?", (email,)):
                st.error("Já existe conta com este email.")
                return
            salt, pw_hash = hash_password(pw1)
            exec_sql(
                "INSERT INTO signup_requests (email, name, salt, password_hash, workspace_name, created_at, status) VALUES (?,?,?,?,?,?,?)",
                (email, name, salt, pw_hash, ws_name, now_utc(), "pending"),
            )
            audit("signup_requested", {"email": email, "workspace_name": ws_name}, workspace_id=None, actor_user_id=None)
            st.success("Solicitação enviada. Aguarde aprovação do Admin.")

    with tabs[2]:
        st.subheader("Aceitar convite")
        email = st.text_input("Seu email", key="inv_email").strip().lower()
        token = st.text_input("Token do convite", key="inv_token").strip()
        if st.button("Aceitar convite", type="primary", key="inv_btn"):
            u = fetchone("SELECT * FROM users WHERE email=?", (email,))
            if not u or not u["is_active"]:
                st.error("Conta inexistente ou não ativa.")
                return
            inv = fetchone("SELECT * FROM invites WHERE token=?", (token,))
            if not inv:
                st.error("Token inválido.")
                return
            if inv.get("used_at"):
                st.error("Convite já utilizado.")
                return
            exp = inv["expires_at"].rstrip("Z")
            if dt.datetime.fromisoformat(exp) < dt.datetime.utcnow():
                st.error("Convite expirado.")
                return
            if inv.get("email_restriction") and inv["email_restriction"].lower() != email:
                st.error("Convite restrito a outro email.")
                return
            # upsert membership
            try:
                exec_sql("INSERT INTO workspace_members (workspace_id, user_id, role, added_at) VALUES (?,?,?,?)",
                         (inv["workspace_id"], u["id"], inv["role"], now_utc()))
            except Exception:
                exec_sql("UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?",
                         (inv["role"], inv["workspace_id"], u["id"]))
            exec_sql("UPDATE invites SET used_by_user_id=?, used_at=? WHERE id=?",
                     (u["id"], now_utc(), inv["id"]))
            audit("invite_accepted", {"invite_id": inv["id"], "role": inv["role"]}, workspace_id=inv["workspace_id"], actor_user_id=u["id"])
            st.success("Convite aceito! Faça login.")
