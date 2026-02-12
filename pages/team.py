import datetime as dt
import streamlit as st
from db import fetchall, fetchone, exec_sql, now_utc
from auth import audit
from pages.common import need_role

def render(workspace_id: int):
    st.header("Equipe & Convites")
    need_role("owner", "Somente owner pode gerenciar equipe/convites.")

    st.subheader("Membros")
    members = fetchall("""
        SELECT wm.user_id, u.email, u.name, wm.role
        FROM workspace_members wm
        JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id=?
        ORDER BY wm.role DESC, u.email COLLATE NOCASE
    """, (workspace_id,))
    if members:
        for m in members:
            cols = st.columns([3,2,1])
            with cols[0]:
                st.write(f"{m['email']} — **{m['role']}**")
            with cols[1]:
                new_role = st.selectbox("Papel", ["viewer","editor","owner"],
                                        index=["viewer","editor","owner"].index(m["role"]) if m["role"] in ["viewer","editor","owner"] else 1,
                                        key=f"role_{m['user_id']}")
            with cols[2]:
                if st.button("Salvar", key=f"save_{m['user_id']}"):
                    exec_sql("UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?",
                             (new_role, workspace_id, m["user_id"]))
                    audit("member_role_updated", {"user_id": m["user_id"], "role": new_role}, workspace_id=workspace_id)
                    st.rerun()
    else:
        st.info("Sem membros?")

    st.divider()
    st.subheader("Gerar convite")
    c1, c2, c3 = st.columns([1,1,2])
    with c1:
        role = st.selectbox("Papel", ["viewer","editor","owner"], index=1, key="inv_role")
    with c2:
        days = st.number_input("Expira (dias)", min_value=1, max_value=90, value=7, step=1, key="inv_days")
    with c3:
        email_restr = st.text_input("Restringir a email (opcional)", value="", key="inv_email_restr")

    if st.button("Gerar token", type="primary"):
        token = __import__("base64").urlsafe_b64encode(__import__("os").urandom(18)).decode().rstrip("=")
        exp = (dt.datetime.utcnow() + dt.timedelta(days=int(days))).replace(microsecond=0).isoformat() + "Z"
        exec_sql("""
            INSERT INTO invites (token, workspace_id, role, email_restriction, created_by_user_id, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?)
        """, (token, workspace_id, role, (email_restr.strip().lower() or None), st.session_state["user"]["id"], now_utc(), exp))
        audit("invite_created", {"role": role, "expires_at": exp, "email_restriction": email_restr}, workspace_id=workspace_id)
        st.success("Token:")
        st.code(token)

    invs = fetchall("SELECT token, role, email_restriction, expires_at, used_at FROM invites WHERE workspace_id=? ORDER BY id DESC LIMIT 20",
                    (workspace_id,))
    if invs:
        st.subheader("Convites recentes")
        st.dataframe(invs, use_container_width=True, hide_index=True)
