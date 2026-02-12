import streamlit as st
from db import fetchall

def render(workspace_id: int):
    st.header("Dashboard")
    st.caption(f"Painel: **{st.session_state.get('workspace_name','')}** • Permissão: **{st.session_state.get('workspace_role','')}**")

    clients = fetchall("SELECT id, name, updated_at FROM clients WHERE workspace_id=? ORDER BY name COLLATE NOCASE", (workspace_id,))
    col1, col2 = st.columns([2,1])
    with col1:
        st.subheader("Clientes")
        if clients:
            st.dataframe(clients, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum cliente ainda.")
    with col2:
        st.subheader("Últimos conteúdos")
        items = fetchall("SELECT id, type, title, created_at FROM content_items WHERE workspace_id=? ORDER BY id DESC LIMIT 8", (workspace_id,))
        if not items:
            st.info("Sem histórico ainda.")
        else:
            for it in items:
                st.markdown(f"**#{it['id']} • {it['type']}**")
                st.caption(f"{it.get('title') or ''} • {it['created_at']}")
