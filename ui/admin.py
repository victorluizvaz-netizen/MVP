import streamlit as st
from db import fetchall, fetchone, exec_sql
import datetime as dt

def _now():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def render(actor_user: dict):
    st.header("Admin")
    if not actor_user.get("is_admin"):
        st.error("Acesso restrito.")
        return

    st.subheader("Solicitações pendentes")
    reqs = fetchall("SELECT * FROM signup_requests WHERE status='pending' ORDER BY id ASC")
    if not reqs:
        st.info("Sem solicitações pendentes.")
        return
    for r in reqs:
        with st.expander(f"#{r['id']} • {r['email']} • {r['workspace_name']}"):
            c1,c2 = st.columns(2)
            with c1:
                if st.button("Aprovar", key=f"apr_{r['id']}", type="primary"):
                    exec_sql("INSERT INTO users (email,name,salt,password_hash,is_admin,is_active,created_at) VALUES (?,?,?,?,?,?,?)",
                             (r["email"], r.get("name"), r["salt"], r["password_hash"], 0, 1, _now()))
                    nu = fetchone("SELECT * FROM users WHERE email=?", (r["email"],))
                    exec_sql("INSERT INTO workspaces (name,created_at,created_by_user_id) VALUES (?,?,?)",
                             (r["workspace_name"], _now(), nu["id"]))
                    ws = fetchone("SELECT * FROM workspaces ORDER BY id DESC LIMIT 1")
                    exec_sql("INSERT INTO workspace_members (workspace_id,user_id,role,added_at) VALUES (?,?,?,?)",
                             (ws["id"], nu["id"], "owner", _now()))
                    exec_sql("UPDATE signup_requests SET status='approved', reviewed_at=? WHERE id=?", (_now(), r["id"]))
                    st.success("Aprovado.")
                    st.rerun()
            with c2:
                if st.button("Rejeitar", key=f"rej_{r['id']}"):
                    exec_sql("UPDATE signup_requests SET status='rejected', reviewed_at=? WHERE id=?", (_now(), r["id"]))
                    st.warning("Rejeitado.")
                    st.rerun()
