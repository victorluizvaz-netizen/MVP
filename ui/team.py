import streamlit as st
import datetime as dt
from db import fetchall, fetchone, exec_sql

def _now():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def render(workspace_id: int, actor_user_id: int, role: str):
    st.header("Equipe")
    members = fetchall("""
        SELECT u.email, u.name, wm.role, wm.added_at
        FROM workspace_members wm JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id=? ORDER BY wm.role, u.email
    """, (workspace_id,))
    st.subheader("Membros")
    st.table([{"email":m["email"],"nome":m.get("name"),"role":m["role"],"desde":m["added_at"]} for m in members])

    if role not in ["owner"]:
        st.info("Apenas owner pode convidar/remover.")
        return

    st.subheader("Criar convite")
    email_restr = st.text_input("Restringir email (opcional)")
    invite_role = st.selectbox("Função", ["viewer","editor"], index=1)
    days = st.number_input("Validade (dias)", 1, 30, 7, 1)
    if st.button("Gerar convite", type="primary"):
        import secrets
        token = secrets.token_urlsafe(20)
        expires = (dt.datetime.utcnow() + dt.timedelta(days=int(days))).replace(microsecond=0).isoformat() + "Z"
        exec_sql("INSERT INTO invites (token,workspace_id,role,email_restriction,created_by_user_id,created_at,expires_at) VALUES (?,?,?,?,?,?,?)",
                 (token, workspace_id, invite_role, (email_restr.strip() or None), actor_user_id, _now(), expires))
        st.success("Convite criado. Copie o token abaixo:")
        st.code(token)
