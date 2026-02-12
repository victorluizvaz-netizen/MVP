import time, datetime as dt
import streamlit as st

from db import init_db
import auth
from db import fetchall

from ui import dashboard, clients, generator, videos, history, team, admin

APP_TITLE = "Content OS — Modular"
st.set_page_config(page_title=APP_TITLE, layout="wide")

init_db()
auth.bootstrap_admin()

st.session_state["_now"] = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
if "last_activity" not in st.session_state:
    st.session_state["last_activity"] = time.time()
if "user" not in st.session_state:
    st.session_state["user"] = None
if "workspace" not in st.session_state:
    st.session_state["workspace"] = None

# restore cookie login
if not st.session_state.get("user"):
    u = auth.restore_user_from_cookie()
    if u:
        st.session_state["user"] = u
        st.session_state["workspace"] = auth.set_active_workspace(u)

# idle timeout
auth.idle_guard()

if not st.session_state.get("user"):
    auth.login_ui()
    st.stop()

u = st.session_state["user"]

# workspace switcher
wss = auth.get_workspaces(u["id"])
if not wss:
    st.error("Você não participa de nenhum painel.")
    st.stop()

ws_ids = [(int(w["id"]), f"#{w['id']} — {w['name']} ({w['role']})") for w in wss]
sel_ws = st.sidebar.selectbox("Painel", ws_ids, format_func=lambda x: x[1], key="ws_sel")
st.session_state["workspace"] = auth.set_active_workspace(u, workspace_id=int(sel_ws[0]))
ws = st.session_state["workspace"]

st.sidebar.markdown(f"**Usuário:** {u['email']}")
if st.sidebar.button("Logout"):
    auth.logout()

menu = ["Dashboard","Clientes","Gerador","Vídeos","Histórico","Equipe"]
if u.get("is_admin"):
    menu.append("Admin")
choice = st.sidebar.radio("Menu", menu)

if choice == "Dashboard":
    dashboard.render(ws["id"])
elif choice == "Clientes":
    if ws["role"] not in ["owner","editor"]:
        st.error("Sem permissão.")
    else:
        clients.render(ws["id"])
elif choice == "Gerador":
    if ws["role"] not in ["owner","editor"]:
        st.error("Sem permissão.")
    else:
        generator.render(ws["id"], u["id"])
elif choice == "Vídeos":
    if ws["role"] not in ["owner","editor"]:
        st.error("Sem permissão.")
    else:
        videos.render(ws["id"], u["id"])
elif choice == "Histórico":
    history.render(ws["id"])
elif choice == "Equipe":
    team.render(ws["id"], u["id"], ws["role"])
elif choice == "Admin":
    admin.render(u)
