import streamlit as st
from db import fetchall
from services.generation import CONTENT_TYPES

def render(workspace_id: int):
    st.header("Histórico")
    clients = fetchall("SELECT id, name FROM clients WHERE workspace_id=? ORDER BY name COLLATE NOCASE", (workspace_id,))
    c1, c2, c3 = st.columns(3)
    with c1:
        client_opt = [{"id": None, "name": "Todos"}] + clients
        sel = st.selectbox("Cliente", client_opt, format_func=lambda x: x["name"], key="hist_client")
        client_id = sel["id"]
    with c2:
        t = st.selectbox("Tipo", ["Todos"] + CONTENT_TYPES, key="hist_type")
    with c3:
        limit = st.number_input("Limite", min_value=10, max_value=500, value=100, step=10, key="hist_limit")

    q = "SELECT * FROM content_items WHERE workspace_id=?"
    params = [workspace_id]
    if client_id:
        q += " AND client_id=?"
        params.append(client_id)
    if t != "Todos":
        q += " AND type=?"
        params.append(t)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))

    items = fetchall(q, tuple(params))
    if not items:
        st.info("Sem itens.")
        return

    for it in items:
        with st.expander(f"#{it['id']} • {it['type']} • {it['created_at']}"):
            st.caption(f"tags: {it.get('tags') or '-'} • model: {it.get('model')}")
            st.text_area("Texto", value=it["output_text"], height=220)
