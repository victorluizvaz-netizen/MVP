import streamlit as st

from db import init_db
from auth import init_session_state, bootstrap_admin, restore_from_cookie, ensure_idle_timeout, login_ui, logout, get_user_workspaces, set_active_workspace, require_role

from pages import dashboard, clients, generator, videos, history, team, admin

APP_TITLE = "Content OS — Modular Build"

st.set_page_config(page_title=APP_TITLE, layout="wide")

init_db()
init_session_state()
bootstrap_admin()
restore_from_cookie()
ensure_idle_timeout(seconds=300)

# Auth gate
if not st.session_state.get("user"):
    login_ui()
    st.stop()

# Sidebar workspace selector
u = st.session_state["user"]
st.sidebar.markdown(f"**Usuário:** {u['email']}")
if u.get("is_admin"):
    st.sidebar.markdown("🛡️ **Admin**")

wss = get_user_workspaces(u["id"])
if wss:
    current = st.session_state.get("workspace_id")
    idx = 0
    if current:
        for i,w in enumerate(wss):
            if w["id"] == current:
                idx = i
                break
    sel = st.sidebar.selectbox("Painel", wss, index=idx, format_func=lambda w: f"#{w['id']} - {w['name']} ({w['role']})")
    set_active_workspace(u["id"], sel["id"])
else:
    st.sidebar.warning("Você ainda não participa de nenhum painel.")

if st.sidebar.button("Logout"):
    logout()

workspace_id = st.session_state.get("workspace_id")
role = st.session_state.get("workspace_role") or "viewer"

pages = ["Dashboard", "Clientes", "Gerador", "Vídeos", "Histórico", "Equipe"]
if u.get("is_admin"):
    pages.append("Admin")

# Hide for viewers
if role == "viewer":
    pages = ["Dashboard", "Histórico"] + (["Admin"] if u.get("is_admin") else [])

# Hide owner-only
if role != "owner" and "Equipe" in pages:
    pages.remove("Equipe")

choice = st.sidebar.radio("Menu", pages)

if choice == "Dashboard":
    dashboard.render(workspace_id)
elif choice == "Clientes":
    clients.render(workspace_id)
elif choice == "Gerador":
    generator.render(workspace_id)
elif choice == "Vídeos":
    videos.render(workspace_id)
elif choice == "Histórico":
    history.render(workspace_id)
elif choice == "Equipe":
    team.render(workspace_id)
elif choice == "Admin":
    admin.render()
