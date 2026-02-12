import os, re, json
import streamlit as st
from db import fetchall, exec_sql
from services.transcription import transcribe_video_bytes
from providers.groq_provider import GroqProvider
from services.generation import CONTENT_TYPES, system_prompt, build_prompt

def render(workspace_id: int, user_id: int):
    st.header("Vídeos")
    clients = fetchall("SELECT * FROM clients WHERE workspace_id=? ORDER BY name", (workspace_id,))
    if not clients:
        st.info("Cadastre um cliente primeiro.")
        return
    client = st.selectbox("Cliente", clients, format_func=lambda c: c["name"], key="vid_client")
    client_id = int(client["id"])

    up = st.file_uploader("Enviar vídeo", type=["mp4","mov","m4v"], key="vid_up")
    if up is not None:
        storage_dir = os.path.join("storage","videos",f"workspace_{workspace_id}",f"client_{client_id}")
        os.makedirs(storage_dir, exist_ok=True)
        safe = re.sub(r"[^a-zA-Z0-9._-]+","_", up.name)
        filepath = os.path.join(storage_dir, safe)
        with open(filepath,"wb") as f:
            f.write(up.getvalue())
        exec_sql("INSERT INTO videos (workspace_id,client_id,filename,filepath,created_at) VALUES (?,?,?,?,?)",
                 (workspace_id, client_id, up.name, filepath, st.session_state.get("_now","")))
        st.success("Vídeo salvo.")
        st.rerun()

    vids = fetchall("SELECT * FROM videos WHERE workspace_id=? AND client_id=? ORDER BY id DESC", (workspace_id, client_id))
    if not vids:
        st.info("Nenhum vídeo ainda.")
        return

    v = st.selectbox("Biblioteca", vids, format_func=lambda x: f"#{x['id']} - {x['filename']}", key="vid_sel")
    video_id = int(v["id"])
    st.caption(v["filepath"])

    c1,c2,c3 = st.columns(3)
    with c1:
        wmodel = st.selectbox("Whisper", ["tiny","base","small"], index=1, key="wh_model")
    with c2:
        lang = st.text_input("Idioma (opcional)", value="", key="wh_lang")
    with c3:
        if st.button("Transcrever", type="primary"):
            with open(v["filepath"],"rb") as f:
                vb = f.read()
            with st.spinner("Transcrevendo..."):
                txt, segs = transcribe_video_bytes(vb, whisper_model=wmodel, language=(lang.strip() or None))
            exec_sql("INSERT INTO transcriptions (workspace_id,video_id,whisper_model,language,text,segments_json,created_at) VALUES (?,?,?,?,?,?,?)",
                     (workspace_id, video_id, wmodel, (lang.strip() or None), txt, json.dumps(segs, ensure_ascii=False), st.session_state.get("_now","")))
            st.success("Transcrito.")
            st.rerun()

    trs = fetchall("SELECT * FROM transcriptions WHERE workspace_id=? AND video_id=? ORDER BY id DESC", (workspace_id, video_id))
    if not trs:
        st.info("Sem transcrições ainda.")
        return
    tr = st.selectbox("Transcrição", trs, format_func=lambda t: f"#{t['id']} • {t['created_at']}", key="tr_sel")
    transcript_text = tr["text"]
    st.text_area("Texto", value=transcript_text, height=160)

    st.subheader("Gerar a partir da transcrição")
    ct = st.selectbox("Tipo", CONTENT_TYPES, key="tr_type")
    n = st.number_input("Quantidade", 1, 20, 3, 1, key="tr_n")
    model = st.selectbox(
    "Modelo (Groq)",
    ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "openai/gpt-oss-120b", "qwen/qwen3-32b"],
    index=0
)
    extra = st.text_area("Extra", height=90, key="tr_extra")

    if st.button("Gerar", type="primary", key="tr_gen"):
        groq = GroqProvider.from_env_or_secrets()
        p = build_prompt(client, ct, int(n), extra=extra, transcript=transcript_text)
        out = groq.chat(model=model, system=system_prompt(client), user=p)
        st.session_state["tr_last"] = {"client_id": client_id, "type": ct, "model": model, "prompt": p, "out": out, "tr_id": int(tr["id"]), "vid_id": video_id}

    lo = st.session_state.get("tr_last")
    if lo:
        out_txt = st.text_area("Saída", value=lo["out"], height=220, key="tr_out")
        if st.button("Salvar no histórico", key="tr_save"):
            exec_sql(
                "INSERT INTO content_items (workspace_id,client_id,type,title,input_source,input_ref,model,prompt_used,output_text,tags,status,created_by_user_id,created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (workspace_id, lo["client_id"], lo["type"], f"{lo['type']} (vídeo #{lo['vid_id']})",
                 "transcription", str(lo["tr_id"]), lo["model"], lo["prompt"], out_txt,
                 f"video:{lo['vid_id']},transcription:{lo['tr_id']}", "draft", user_id, st.session_state.get("_now",""))
            )
            st.success("Salvo.")
            st.session_state["tr_last"] = None
            st.rerun()
