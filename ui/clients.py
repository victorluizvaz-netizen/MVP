import streamlit as st
from db import fetchall, fetchone, exec_sql

def render(workspace_id: int):
    st.header("Clientes")

    rows = fetchall("SELECT id,name,description,updated_at FROM clients WHERE workspace_id=? ORDER BY name", (workspace_id,))
    options = [(-1, "(novo)")] + [(int(r["id"]), r["name"]) for r in rows]
    sel = st.selectbox("Selecionar", options, format_func=lambda x: x[1], key="client_select")
    client_id = int(sel[0])

    if client_id == -1:
        st.subheader("Novo cliente")
        name = st.text_input("Nome", key="c_new_name")
        desc = st.text_area("Descrição", height=140, key="c_new_desc")
        sp = st.text_area("System prompt (opcional)", height=120, key="c_new_sp")
        if st.button("Criar", type="primary"):
            if not name.strip():
                st.error("Nome obrigatório.")
                st.stop()
            exec_sql(
                "INSERT INTO clients (workspace_id,name,description,system_prompt,templates_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (workspace_id, name.strip(), desc, sp, "{}", st.session_state.get("_now",""), st.session_state.get("_now",""))
            )
            st.success("Cliente criado.")
            st.rerun()
        return

    c = fetchone("SELECT * FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id))
    if not c:
        st.error("Cliente não encontrado.")
        st.stop()

    st.subheader(f"Editar: {c['name']}")
    name = st.text_input("Nome", value=c.get("name") or "", key="c_ed_name")
    desc = st.text_area("Descrição", value=c.get("description") or "", height=140, key="c_ed_desc")
    sp = st.text_area("System prompt (opcional)", value=c.get("system_prompt") or "", height=120, key="c_ed_sp")

    col1,col2 = st.columns([1,1])
    with col1:
        if st.button("Salvar alterações", type="primary"):
            exec_sql("UPDATE clients SET name=?, description=?, system_prompt=?, updated_at=? WHERE workspace_id=? AND id=?",
                     (name.strip(), desc, sp, st.session_state.get("_now",""), workspace_id, client_id))
            st.success("Atualizado.")
            st.rerun()
    with col2:
        if st.button("Excluir", type="secondary"):
            exec_sql("DELETE FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id))
            st.warning("Excluído.")
            st.rerun()
