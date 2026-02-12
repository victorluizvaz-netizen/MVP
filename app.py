import os
import streamlit as st

st.set_page_config(page_title="Content OS (Stable Build)", layout="wide")

# Session init
for k in ["user", "workspace_id"]:
    if k not in st.session_state:
        st.session_state[k] = None

st.title("Content OS — Stable Build")

if not st.session_state.get("user"):
    st.subheader("Login (demo)")
    email = st.text_input("Email")
    senha = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        st.session_state["user"] = {"email": email}
        st.session_state["workspace_id"] = 1
        st.rerun()
    st.stop()

st.success(f"Logado como {st.session_state['user']['email']}")
st.write("Sistema estável carregado sem erros de sintaxe/indentação.")
