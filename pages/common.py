import streamlit as st
from auth import require_role

def deny(msg: str = "Sem permissão."):
    st.error(msg)
    st.stop()

def need_role(min_role: str, msg: str):
    if not require_role(min_role):
        deny(msg)
