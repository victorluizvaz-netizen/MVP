import streamlit as st
from db import fetchall, exec_sql
from providers.groq_provider import GroqProvider
from services.generation import CONTENT_TYPES, system_prompt, build_prompt

def render(workspace_id: int, user_id: int):
    st.header("Gerador")
    clients = fetchall("SELECT * FROM clients WHERE workspace_id=? ORDER BY name", (workspace_id,))
    if not clients:
        st.info("Cadastre um cliente primeiro.")
        return

    client = st.selectbox("Cliente", clients, format_func=lambda c: c["name"], key="gen_client")
    ct = st.selectbox("Tipo", CONTENT_TYPES, key="gen_type")
    n = st.number_input("Quantidade", 1, 20, 3, 1, key="gen_n")
    model = st.selectbox("Modelo (Groq)",["groq-1.5-1-mini", "groq-1.5-1-base", "groq-1.5-1-large"],index=1)
    extra = st.text_area("Extra (opcional)", height=120, key="gen_extra")

    if st.button("Gerar", type="primary"):
        try:
            groq = GroqProvider.from_env_or_secrets()
        except Exception as e:
            st.error(f"Groq indisponível: {e}")
            st.stop()
        p = build_prompt(client, ct, int(n), extra=extra)
        out = groq.chat(model=model, system=system_prompt(client), user=p)
        st.session_state["gen_last"] = {"client_id": int(client["id"]), "type": ct, "model": model, "prompt": p, "out": out}

    lo = st.session_state.get("gen_last")
    if lo:
        out_txt = st.text_area("Saída", value=lo["out"], height=260, key="gen_out")
        if st.button("Salvar no histórico"):
            exec_sql(
                "INSERT INTO content_items (workspace_id,client_id,type,title,input_source,input_ref,model,prompt_used,output_text,tags,status,created_by_user_id,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (workspace_id, lo["client_id"], lo["type"], f"{lo['type']} (manual)", "manual", None, lo["model"],
                 lo["prompt"], out_txt, "", "draft", user_id, st.session_state.get("_now",""))
            )
            st.success("Salvo.")
            st.session_state["gen_last"] = None
            st.rerun()
