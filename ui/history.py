import streamlit as st
from db import fetchall

def render(workspace_id: int):
    st.header("Histórico")
    items = fetchall("SELECT id,type,title,created_at,tags,output_text FROM content_items WHERE workspace_id=? ORDER BY id DESC LIMIT 100",
                     (workspace_id,))
    if not items:
        st.info("Sem histórico ainda.")
        return
    for it in items:
        with st.expander(f"#{it['id']} • {it['type']} • {it.get('created_at','')}"):
            if it.get("tags"):
                st.caption(it["tags"])
            st.text_area("Texto", value=it["output_text"], height=200)
