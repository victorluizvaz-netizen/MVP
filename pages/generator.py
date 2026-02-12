import streamlit as st
from db import fetchall, exec_sql, now_utc
from auth import audit
from pages.common import need_role
from providers.groq import GroqProvider
from services.generation import CONTENT_TYPES, build_prompt

MODELS = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant"]

def render(workspace_id: int):
    st.header("Gerador")
    need_role("editor", "Somente owner/editor pode gerar conteúdo.")

    clients = fetchall("SELECT * FROM clients WHERE workspace_id=? ORDER BY name COLLATE NOCASE", (workspace_id,))
    if not clients:
        st.info("Cadastre um cliente primeiro.")
        return

    client = st.selectbox("Cliente", clients, format_func=lambda c: f"#{c['id']} - {c['name']}", key="gen_client")
    client_id = int(client["id"])

    c1, c2, c3 = st.columns(3)
    with c1:
        ctype = st.selectbox("Tipo", CONTENT_TYPES, key="gen_type")
    with c2:
        n = st.number_input("Quantidade", min_value=1, max_value=20, value=3, step=1, key="gen_n")
    with c3:
        model = st.selectbox("Modelo (Groq)", MODELS, index=0, key="gen_model")

    extra = st.text_area("Contexto extra (opcional)", height=120, key="gen_extra")

    if "last_gen" not in st.session_state:
        st.session_state["last_gen"] = None

    if st.button("Gerar", type="primary"):
        try:
            provider = GroqProvider.from_env_or_secrets()
        except Exception as e:
            st.error(f"Groq indisponível: {e}")
            st.stop()

        sys, user_prompt, prompt_used = build_prompt(client, ctype, int(n), extra=extra, transcript="")
        with st.spinner("Gerando..."):
            out = provider.chat(model=model, system=sys, user=user_prompt)

        st.session_state["last_gen"] = {
            "client_id": client_id,
            "type": ctype,
            "title": f"{ctype} — {client['name']}",
            "provider": "groq",
            "model": model,
            "prompt_used": prompt_used,
            "output_text": out.strip(),
            "tags": "",
            "input_source": "manual",
            "input_ref": None,
        }
        audit("content_generated", {"type": ctype, "client_id": client_id, "model": model}, workspace_id=workspace_id)
        st.rerun()

    lg = st.session_state.get("last_gen")
    if lg and lg.get("client_id") == client_id:
        st.divider()
        st.subheader("Resultado")
        out_val = st.text_area("Texto", value=lg["output_text"], height=260, key="gen_out")
        title = st.text_input("Título", value=lg["title"], key="gen_title")
        tags = st.text_input("Tags (vírgula)", value=lg.get("tags",""), key="gen_tags")

        if st.button("Salvar no histórico", type="primary"):
            exec_sql("""
                INSERT INTO content_items (workspace_id, client_id, type, title, input_source, input_ref,
                                          provider, model, prompt_used, output_text, tags, status, created_by_user_id, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (workspace_id, client_id, lg["type"], title.strip(), lg["input_source"], lg["input_ref"],
                    lg["provider"], lg["model"], lg["prompt_used"], out_val, tags.strip(), "draft",
                    st.session_state["user"]["id"], now_utc()))
            audit("content_saved", {"type": lg["type"], "client_id": client_id}, workspace_id=workspace_id)
            st.success("Salvo.")
            st.session_state["last_gen"] = None
            st.rerun()

        if st.button("Limpar"):
            st.session_state["last_gen"] = None
            st.rerun()
