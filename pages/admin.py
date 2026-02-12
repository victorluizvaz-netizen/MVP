import streamlit as st
from db import fetchall, fetchone, exec_sql, now_utc
from auth import audit, hash_password

def render():
    st.header("Admin")
    u = st.session_state.get("user") or {}
    if not u.get("is_admin"):
        st.error("Acesso restrito.")
        st.stop()

    tabs = st.tabs(["Aprovar contas", "Usuários", "Auditoria"])
    with tabs[0]:
        st.subheader("Solicitações pendentes")
        reqs = fetchall("SELECT * FROM signup_requests WHERE status='pending' ORDER BY id ASC")
        if not reqs:
            st.info("Sem solicitações.")
        else:
            for r in reqs:
                with st.expander(f"#{r['id']} • {r['email']} • {r['workspace_name']}"):
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("Aprovar", type="primary", key=f"apr_{r['id']}"):
                            exec_sql("""
                                INSERT INTO users (email, name, salt, password_hash, is_admin, is_active, created_at)
                                VALUES (?,?,?,?,?,?,?)
                            """, (r["email"], r.get("name"), r["salt"], r["password_hash"], 0, 1, now_utc()))
                            u2 = fetchone("SELECT * FROM users WHERE email=?", (r["email"],))
                            exec_sql("INSERT INTO workspaces (name, created_at, created_by_user_id) VALUES (?,?,?)",
                                     (r["workspace_name"], now_utc(), u2["id"]))
                            ws = fetchone("SELECT * FROM workspaces ORDER BY id DESC LIMIT 1")
                            exec_sql("INSERT INTO workspace_members (workspace_id, user_id, role, added_at) VALUES (?,?,?,?)",
                                     (ws["id"], u2["id"], "owner", now_utc()))
                            exec_sql("UPDATE signup_requests SET status='approved', reviewed_at=? WHERE id=?",
                                     (now_utc(), r["id"]))
                            audit("signup_approved", {"request_id": r["id"], "user_id": u2["id"], "workspace_id": ws["id"]},
                                  workspace_id=ws["id"], actor_user_id=u["id"])
                            st.success("Aprovado.")
                            st.rerun()
                    with c2:
                        if st.button("Rejeitar", key=f"rej_{r['id']}"):
                            exec_sql("UPDATE signup_requests SET status='rejected', reviewed_at=? WHERE id=?",
                                     (now_utc(), r["id"]))
                            audit("signup_rejected", {"request_id": r["id"], "email": r["email"]}, workspace_id=None, actor_user_id=u["id"])
                            st.warning("Rejeitado.")
                            st.rerun()

    with tabs[1]:
        st.subheader("Usuários")
        users = fetchall("SELECT id, email, is_admin, is_active, created_at FROM users ORDER BY id DESC LIMIT 200")
        for usr in users:
            cols = st.columns([3,1,1])
            with cols[0]:
                st.write(f"{usr['email']} • id {usr['id']}")
                st.caption(f"ativo: {usr['is_active']} • admin: {usr['is_admin']} • {usr['created_at']}")
            with cols[1]:
                if st.button(("Desativar" if usr["is_active"] else "Ativar"), key=f"act_{usr['id']}"):
                    exec_sql("UPDATE users SET is_active=? WHERE id=?", (0 if usr["is_active"] else 1, usr["id"]))
                    audit("user_active_toggled", {"user_id": usr["id"]}, workspace_id=None, actor_user_id=u["id"])
                    st.rerun()
            with cols[2]:
                if st.button(("Remover admin" if usr["is_admin"] else "Tornar admin"), key=f"adm_{usr['id']}"):
                    exec_sql("UPDATE users SET is_admin=? WHERE id=?", (0 if usr["is_admin"] else 1, usr["id"]))
                    audit("user_admin_toggled", {"user_id": usr["id"]}, workspace_id=None, actor_user_id=u["id"])
                    st.rerun()

    with tabs[2]:
        st.subheader("Auditoria")
        logs = fetchall("SELECT * FROM audit_log ORDER BY id DESC LIMIT 200")
        st.dataframe([{
            "quando": l["created_at"],
            "workspace": l.get("workspace_id"),
            "ator": l.get("actor_user_id"),
            "ação": l["action"],
            "detalhes": l.get("details_json") or ""
        } for l in logs], use_container_width=True, hide_index=True)
