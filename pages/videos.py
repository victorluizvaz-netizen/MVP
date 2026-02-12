import os, re, json
import streamlit as st
from db import fetchall, fetchone, exec_sql, now_utc
from auth import audit
from pages.common import need_role
from services.transcription import transcribe_video_bytes
from providers.groq import GroqProvider
from services.generation import CONTENT_TYPES, build_prompt

MODELS = ["llama-3.1-70b-versatile", "llama-3.1-8b-instant"]

def render(workspace_id: int):
    st.header("Vídeos")
    need_role("editor", "Somente owner/editor pode usar vídeos.")

    clients = fetchall("SELECT id, name FROM clients WHERE workspace_id=? ORDER BY name COLLATE NOCASE", (workspace_id,))
    if not clients:
        st.info("Cadastre um cliente primeiro.")
        return
    client = st.selectbox("Cliente", clients, format_func=lambda c: f"#{c['id']} - {c['name']}", key="vid_client")
    client_id = int(client["id"])

    st.subheader("Upload")
    up = st.file_uploader("Envie um vídeo (mp4/mov)", type=["mp4","mov","m4v"], key="vid_upload")
    if up is not None:
        storage_dir = os.path.join("storage", "videos", f"workspace_{workspace_id}", f"client_{client_id}")
        os.makedirs(storage_dir, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", up.name)
        filepath = os.path.join(storage_dir, f"{int(__import__('time').time())}_{safe}")
        with open(filepath, "wb") as f:
            f.write(up.getvalue())
        exec_sql("INSERT INTO videos (workspace_id, client_id, filename, filepath, created_at) VALUES (?,?,?,?,?)",
                 (workspace_id, client_id, up.name, filepath, now_utc()))
        vid_id = fetchone("SELECT id FROM videos WHERE workspace_id=? ORDER BY id DESC LIMIT 1", (workspace_id,))["id"]
        audit("video_uploaded", {"video_id": vid_id}, workspace_id=workspace_id)
        st.success(f"Vídeo salvo (#{vid_id}).")
        st.rerun()

    vids = fetchall("SELECT * FROM videos WHERE workspace_id=? AND client_id=? ORDER BY id DESC", (workspace_id, client_id))
    st.divider()
    st.subheader("Biblioteca")
    if not vids:
        st.info("Nenhum vídeo ainda.")
        return

    v = st.radio("Selecione um vídeo", vids, format_func=lambda x: f"#{x['id']} - {x['filename']}", key="vid_sel")
    video_id = int(v["id"])
    st.caption(v["filepath"])

    st.subheader("Transcrição (Whisper)")
    tlist = fetchall("SELECT * FROM transcriptions WHERE workspace_id=? AND video_id=? ORDER BY id DESC", (workspace_id, video_id))
    c1, c2, c3 = st.columns(3)
    with c1:
        wh_model = st.selectbox("Modelo Whisper", ["tiny","base","small"], index=1, key="wh_model")
    with c2:
        lang = st.text_input("Idioma (opcional, ex: pt)", value="", key="wh_lang")
    with c3:
        if st.button("Transcrever", type="primary"):
            with open(v["filepath"], "rb") as f:
                vb = f.read()
            with st.spinner("Transcrevendo..."):
                text, seg = transcribe_video_bytes(vb, whisper_model=wh_model, language=(lang.strip() or None))
            exec_sql("""
                INSERT INTO transcriptions (workspace_id, video_id, engine, language, whisper_model, text, segments_json, created_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (workspace_id, video_id, "whisper", (lang.strip() or None), wh_model, text, json.dumps(seg, ensure_ascii=False), now_utc()))
            tid = fetchone("SELECT id FROM transcriptions WHERE workspace_id=? ORDER BY id DESC LIMIT 1", (workspace_id,))["id"]
            audit("transcription_created", {"transcription_id": tid, "video_id": video_id}, workspace_id=workspace_id)
            st.success(f"Transcrição criada (#{tid}).")
            st.rerun()

    if not tlist:
        st.info("Sem transcrições ainda.")
        return

    tr = st.selectbox("Escolha uma transcrição", tlist, format_func=lambda t: f"#{t['id']} • {t['created_at']} • {t.get('whisper_model')}", key="tr_sel")
    transcript_text = tr["text"]
    transcription_id = int(tr["id"])
    st.text_area("Texto", value=transcript_text, height=170)

    st.subheader("Gerar conteúdo a partir da transcrição")
    g1, g2, g3 = st.columns(3)
    with g1:
        ctype = st.selectbox("Tipo", CONTENT_TYPES, key="tr_type")
    with g2:
        n = st.number_input("Qtd", min_value=1, max_value=20, value=3, step=1, key="tr_n")
    with g3:
        model = st.selectbox("Modelo (Groq)", MODELS, index=0, key="tr_model")

    extra = st.text_area("Contexto extra", height=90, key="tr_extra")

    if st.button("Gerar", type="primary", key="tr_generate"):
        try:
            provider = GroqProvider.from_env_or_secrets()
        except Exception as e:
            st.error(f"Groq indisponível: {e}")
            st.stop()
        client_full = fetchone("SELECT * FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id))
        sys, user_prompt, prompt_used = build_prompt(client_full, ctype, int(n), extra=extra, transcript=transcript_text)
        with st.spinner("Gerando..."):
            out = provider.chat(model=model, system=sys, user=user_prompt)

        tags = f"video:{video_id},transcription:{transcription_id}"
        exec_sql("""
            INSERT INTO content_items (workspace_id, client_id, type, title, input_source, input_ref,
                                      provider, model, prompt_used, output_text, tags, status, created_by_user_id, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (workspace_id, client_id, ctype, f"{ctype} — {client['name']} (vídeo #{video_id})",
                "transcription", str(transcription_id), "groq", model, prompt_used, out.strip(), tags,
                "draft", st.session_state["user"]["id"], now_utc()))
        audit("content_saved_from_transcription", {"client_id": client_id, "video_id": video_id}, workspace_id=workspace_id)
        st.success("Salvo no histórico.")
        st.rerun()
