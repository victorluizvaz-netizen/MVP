import streamlit as st
from db import fetchall

def render(workspace_id: int):
    st.header("Dashboard")
    clients = fetchall("SELECT id,name FROM clients WHERE workspace_id=? ORDER BY name", (workspace_id,))
    st.metric("Clientes", len(clients))
