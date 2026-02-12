
import json
from datetime import datetime
from pathlib import Path
import streamlit as st

from app import db
from app.providers.groq_provider import GroqProvider
from app.services.transcription_service import transcribe_video_bytes
from app.services.content_service import run_task, build_instruction, get_system_prompt, DEFAULT_TEMPLATES

APP_STORAGE = Path("storage")
VIDEOS_DIR = APP_STORAGE / "videos"

st.set_page_config(page_title="Content OS (Instagram)", layout="wide", page_icon="🧠")
db.init_db()

# ---------- providers ----------
@st.cache_resource
def load_providers():
    providers = {}
    providers["groq"] = GroqProvider()
    return providers

try:
    providers = load_providers()
except Exception as e:
    providers = {"groq_error": str(e)}

CONTENT_TYPES = ["Ideias", "Copy Reels", "Carrossel", "Campanha", "Stories", "Roteiro"]
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

def require_client(current_client):
    if not current_client:
        st.info("Selecione um cliente no menu lateral (ou crie em **Clientes**).")
        st.stop()

def provider_ready():
    if "groq" not in providers:
        st.error("Groq indisponível: " + str(providers.get("groq_error", "sem detalhes")))
        st.stop()
    return providers["groq"]

def save_generation(client_id, ctype, title, prompt_used, output_text, model, input_source="manual", input_ref=None, tags=""):
    db.add_content_item(
        client_id=client_id,
        type_=ctype,
        title=title or "",
        input_source=input_source,
        input_ref=input_ref,
        provider="groq",
        model=model,
        prompt_used=prompt_used,
        output_text=output_text,
        status="draft",
        tags=tags or "",
    )

# ---------- sidebar ----------
clients = db.list_clients()
client_names = ["— selecione —"] + [c["name"] for c in clients]
name_to_id = {c["name"]: c["id"] for c in clients}

with st.sidebar:
    st.title("🧠 Content OS")
    sel_name = st.selectbox("Cliente", client_names, index=0)
    page = st.radio("Páginas", ["Dashboard", "Clientes", "Gerador", "Vídeos", "Rotinas", "Histórico"], index=0)
    st.caption("Whisper (transcrição) + Groq (conteúdo)")

current_client = None if sel_name == "— selecione —" else db.get_client(name_to_id[sel_name])

# ---------- PAGES ----------
if page == "Dashboard":
    st.header("Dashboard")
    if not current_client:
        st.info("Selecione um cliente ou crie um novo em **Clientes**.")
    else:
        st.subheader(f"Cliente: {current_client['name']}")
        st.write(current_client.get("description",""))

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Vídeos", len(db.list_videos(current_client["id"])))
        with col2:
            st.metric("Conteúdos", len(db.list_content_items(current_client["id"], limit=9999)))
        with col3:
            st.metric("Rotinas", len(db.list_schedules(current_client["id"])))
        with col4:
            st.metric("Provider", "Groq" if "groq" in providers else "—")

        st.divider()
        st.markdown("### Atalhos")
        a,b,c,d = st.columns(4)
        with a:
            st.write("Gerar conteúdo rápido")
            if st.button("➕ Novo conteúdo", use_container_width=True):
                st.session_state["_goto"]="Gerador"
        with b:
            st.write("Enviar vídeo")
            if st.button("📼 Upload + Transcrever", use_container_width=True):
                st.session_state["_goto"]="Vídeos"
        with c:
            st.write("Criar rotina")
            if st.button("🗓️ Rotinas", use_container_width=True):
                st.session_state["_goto"]="Rotinas"
        with d:
            st.write("Ver histórico")
            if st.button("🗂️ Histórico", use_container_width=True):
                st.session_state["_goto"]="Histórico"

        if st.session_state.get("_goto"):
            st.caption(f"Abra a página **{st.session_state['_goto']}** no menu lateral.")

elif page == "Clientes":
    st.header("Clientes")
    tab1, tab2 = st.tabs(["Criar/Editar", "Lista"])

    with tab1:
        edit_client = current_client
        if edit_client:
            st.subheader("Editar cliente selecionado")
            cid = edit_client["id"]
            default_name = edit_client["name"]
            default_desc = edit_client.get("description","")
            default_profile = edit_client.get("profile") or {}
        else:
            st.subheader("Criar novo cliente")
            cid = None
            default_name = ""
            default_desc = ""
            default_profile = {}

        name = st.text_input("Nome", value=default_name, placeholder="Ex.: Prolicitante")
        desc = st.text_area("Descrição", value=default_desc, height=120)

        st.markdown("### Perfil (guia rápido)")
        colA, colB = st.columns(2)
        with colA:
            nicho = st.text_input("Nicho", value=default_profile.get("nicho",""), placeholder="Consultoria em licitações")
            publico = st.text_input("Público", value=default_profile.get("publico",""), placeholder="Empresas que vendem para o governo")
            tom = st.text_input("Tom de voz", value=default_profile.get("tom_de_voz",""), placeholder="Claro, objetivo, autoridade, sem juridiquês pesado")
            cta = st.text_input("CTA padrão", value=default_profile.get("cta",""), placeholder="Chame no WhatsApp para diagnóstico")
        with colB:
            oferta = st.text_area("Oferta/Serviço", value=default_profile.get("oferta",""), height=70)
            diferenciais = st.text_area("Diferenciais", value=default_profile.get("diferenciais",""), height=70)
            restricoes = st.text_area("Restrições (não falar / não prometer)", value=default_profile.get("restricoes",""), height=70)

        st.markdown("### Presets (pra gerar sempre no padrão)")
        system_prompt = st.text_area(
            "System prompt do cliente (opcional)",
            value=default_profile.get("system_prompt",""),
            height=120,
            placeholder="Ex.: Você é social media para empresa de licitações. Linguagem clara, autoridade, com exemplos práticos, sem prometer resultados..."
        )

        st.markdown("### Preferências por tipo de conteúdo (opcional)")
        st.caption("Se você preencher, isso sobrescreve o template padrão daquele tipo.")
        format_prefs = default_profile.get("format_prefs") or {}
        prefs_out = {}
        for ctype in CONTENT_TYPES:
            with st.expander(f"Template para: {ctype}", expanded=False):
                txt = st.text_area(
                    f"Instrução/template ({ctype})",
                    value=format_prefs.get(ctype, ""),
                    height=110,
                    placeholder=DEFAULT_TEMPLATES.get(ctype, "")
                )
                if txt.strip():
                    prefs_out[ctype]=txt.strip()

        profile = {
            "nicho": nicho,
            "publico": publico,
            "tom_de_voz": tom,
            "cta": cta,
            "oferta": oferta,
            "diferenciais": diferenciais,
            "restricoes": restricoes,
            "system_prompt": system_prompt,
            "format_prefs": prefs_out,
        }

        colS1, colS2 = st.columns([1,1])
        with colS1:
            if st.button("💾 Salvar", use_container_width=True):
                if not name.strip():
                    st.error("Informe um nome.")
                else:
                    try:
                        db.upsert_client(name=name, description=desc, profile=profile, client_id=cid)
                        st.success("Salvo! Recarregue (F5) para atualizar o seletor de cliente.")
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
        with colS2:
            if cid is not None and st.button("🗑️ Excluir cliente", use_container_width=True):
                db.delete_client(cid)
                st.warning("Cliente excluído. Recarregue (F5).")

    with tab2:
        st.subheader("Clientes cadastrados")
        st.dataframe(db.list_clients(), use_container_width=True)

elif page == "Gerador":
    st.header("Gerador de Conteúdo")
    require_client(current_client)
    provider = provider_ready()

    st.subheader(f"Cliente: {current_client['name']}")

    col1, col2, col3, col4 = st.columns([2,2,1,1])
    with col1:
        content_type = st.selectbox("Tipo", CONTENT_TYPES, index=0)
    with col2:
        model = st.selectbox("Modelo (Groq)", provider.available_models(), index=0)
    with col3:
        n = st.number_input("Qtd", min_value=1, max_value=20, value=3, step=1)
    with col4:
        temperature = st.slider("Temperatura", 0.0, 1.2, 0.35, 0.05)

    extra = st.text_area("Contexto extra (opcional)", height=100, placeholder="Ex.: foco em captação no WhatsApp, mencionar diagnóstico, dor X, etc.")
    instruction_preview = build_instruction(current_client, content_type, n=int(n), extra=extra)
    with st.expander("Ver instrução que será enviada (preview)", expanded=False):
        st.code(instruction_preview)

    st.markdown("### Gerar")
    colA, colB = st.columns([2,1])
    with colA:
        mode = st.radio("Fonte de conteúdo", ["Manual", "Usar transcrição de um vídeo"], horizontal=True)
    transcription_id = None
    input_text = ""
    if mode == "Usar transcrição de um vídeo":
        vids = db.list_videos(current_client["id"])
        if not vids:
            st.warning("Este cliente ainda não tem vídeos.")
        else:
            vid_label = [f"#{v['id']} — {v['filename']} ({v['created_at']})" for v in vids]
            sel_vid = st.selectbox("Escolha um vídeo", vid_label, index=0)
            vid_id = int(sel_vid.split("—")[0].strip().replace("#",""))
            trans = db.list_transcriptions_for_video(vid_id)
            if not trans:
                st.warning("Vídeo ainda não foi transcrito. Vá em **Vídeos** e transcreva.")
            else:
                tlabel = [f"Transcrição #{t['id']} ({t['created_at']})" for t in trans]
                sel_t = st.selectbox("Escolha a transcrição", tlabel, index=0)
                transcription_id = int(sel_t.split("#")[1].split()[0])
                t = db.get_transcription(transcription_id)
                input_text = (t or {}).get("text","")
                with st.expander("Ver transcrição", expanded=False):
                    st.text_area("Transcrição", value=input_text, height=200)

    run = st.button("✨ Gerar agora", type="primary", use_container_width=True)
    if run:
        sys_prompt = get_system_prompt(current_client)
        with st.spinner("Gerando..."):
            output = run_task(
                provider=provider,
                model=model,
                client=current_client,
                instruction=instruction_preview,
                input_text=input_text,
                temperature=float(temperature),
                system_prompt=sys_prompt,
            )
        st.success("Pronto!")
        st.markdown(output)

        # salvar
        title = st.text_input("Título (opcional) para salvar no histórico", value=f"{content_type} — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        tags = st.text_input("Tags (opcional)", value="")
        if st.button("💾 Salvar no histórico", use_container_width=True):
            save_generation(
                client_id=current_client["id"],
                ctype=content_type,
                title=title,
                prompt_used=instruction_preview,
                output_text=output,
                model=model,
                input_source="transcription" if transcription_id else "manual",
                input_ref=transcription_id,
                tags=tags,
            )
            st.success("Salvo!")

elif page == "Vídeos":
    st.header("Vídeos & Transcrições")
    require_client(current_client)
    provider = provider_ready()

    st.subheader(f"Cliente: {current_client['name']}")

    # upload
    st.markdown("### Upload")
    up = st.file_uploader("Envie um vídeo (mp4/mov)", type=["mp4","mov","m4v","avi","webm"])
    whisper_model = st.selectbox("Modelo Whisper", ["tiny","base","small","medium"], index=1)
    language = st.selectbox("Idioma", ["pt", "auto"], index=0)

    if up and st.button("📝 Salvar e Transcrever", type="primary"):
        client_dir = VIDEOS_DIR / f"client_{current_client['id']}"
        client_dir.mkdir(parents=True, exist_ok=True)
        filepath = client_dir / up.name
        filepath.write_bytes(up.getvalue())
        vid_id = db.add_video(current_client["id"], up.name, filepath.as_posix())

        with st.spinner("Transcrevendo com Whisper..."):
            text, segments = transcribe_video_bytes(up.getvalue(), whisper_model=whisper_model, language=None if language=="auto" else language)
        t_id = db.add_transcription(video_id=vid_id, text=text, segments=segments, engine="whisper")
        st.success(f"Transcrição salva! (Vídeo #{vid_id} / Transcrição #{t_id})")

    st.divider()

    vids = db.list_videos(current_client["id"])
    if not vids:
        st.info("Nenhum vídeo cadastrado ainda.")
        st.stop()

    left, right = st.columns([1,2])
    with left:
        st.markdown("### Biblioteca")
        labels = [f"#{v['id']} — {v['filename']}" for v in vids]
        sel = st.radio("Selecione um vídeo", labels, index=0)
        video_id = int(sel.split("—")[0].strip().replace("#",""))
        v = db.get_video(video_id)

    with right:
        st.markdown("### Detalhes do vídeo")
        st.write(f"**Arquivo:** {v['filename']}")
        st.caption(f"Criado em: {v['created_at']}")
        # tentar exibir vídeo
        try:
            st.video(Path(v["filepath"]).read_bytes())
        except Exception:
            st.info("Pré-visualização indisponível neste ambiente (arquivo grande ou codec).")

        trans_list = db.list_transcriptions_for_video(video_id)
        st.markdown("#### Transcrições")
        if not trans_list:
            st.warning("Este vídeo ainda não tem transcrição.")
        else:
            tlabels = [f"#{t['id']} — {t['created_at']}" for t in trans_list]
            sel_t = st.selectbox("Escolha", tlabels, index=0)
            tid = int(sel_t.split("—")[0].strip().replace("#",""))
            t = db.get_transcription(tid)
            st.text_area("Texto", value=(t or {}).get("text",""), height=220)

            st.markdown("#### Gerar conteúdo a partir desta transcrição")
            ctype = st.selectbox("Tipo", CONTENT_TYPES, index=1, key="vctype")
            n = st.number_input("Qtd", 1, 20, 3, 1, key="vc_n")
            model = st.selectbox("Modelo (Groq)", provider.available_models(), index=0, key="vc_model")
            temperature = st.slider("Temperatura", 0.0, 1.2, 0.35, 0.05, key="vc_temp")
            extra = st.text_area("Contexto extra (opcional)", height=80, key="vc_extra")

            instr = build_instruction(current_client, ctype, n=int(n), extra=extra)
            with st.expander("Preview da instrução", expanded=False):
                st.code(instr)

            if st.button("✨ Gerar do vídeo", type="primary", use_container_width=True):
                sys_prompt = get_system_prompt(current_client)
                with st.spinner("Gerando..."):
                    output = run_task(
                        provider=provider,
                        model=model,
                        client=current_client,
                        instruction=instr,
                        input_text=(t or {}).get("text",""),
                        temperature=float(temperature),
                        system_prompt=sys_prompt,
                    )
                st.success("Pronto!")
                st.markdown(output)
                title = f"{ctype} — vídeo #{video_id}"
                save_generation(
                    client_id=current_client["id"],
                    ctype_=ctype,
                    title=title,
                    prompt_used=instr,
                    output_text=output,
                    model=model,
                    input_source="transcription",
                    input_ref=tid,
                    tags=f"video:{video_id}",
                )
                st.caption("Salvo automaticamente no histórico (tag video:ID).")

        st.divider()
        st.markdown("#### Conteúdos gerados deste vídeo")
        # buscar content items com tags contendo video:{id} ou input_ref em transcrições
        items = db.list_content_items(current_client["id"], limit=200)
        related=[]
        for it in items:
            if f"video:{video_id}" in (it.get("tags") or ""):
                related.append(it)
            else:
                # se input_ref refere a transcrição do vídeo
                if it.get("input_ref"):
                    tr = db.get_transcription(int(it["input_ref"]))
                    if tr and tr.get("video_id")==video_id:
                        related.append(it)
        if not related:
            st.caption("Ainda não há conteúdos vinculados a este vídeo.")
        else:
            for it in related[:30]:
                with st.expander(f"[{it['type']}] {it.get('title','')} — {it['created_at']}", expanded=False):
                    st.caption(f"Modelo: {it['model']} | Tags: {it.get('tags','')}")
                    st.code(it.get("prompt_used",""))
                    st.markdown(it.get("output_text",""))

elif page == "Rotinas":
    st.header("Rotinas (segunda-feira etc.)")
    require_client(current_client)
    provider = provider_ready()

    st.subheader(f"Cliente: {current_client['name']}")
    st.caption("No Streamlit, o agendamento automático depende do deploy. Aqui você configura e executa com um clique (MVP).")

    schedules = db.list_schedules(current_client["id"])
    tab1, tab2 = st.tabs(["Criar/Editar", "Executar"])

    with tab1:
        st.markdown("### Nova rotina")
        colA, colB, colC = st.columns([1,1,2])
        with colA:
            weekday = st.selectbox("Dia da semana", list(range(7)), format_func=lambda i: WEEKDAYS[i], index=0)
        with colB:
            hour = st.number_input("Hora", 0, 23, 9, 1)
            minute = st.number_input("Minuto", 0, 59, 0, 5)
        with colC:
            model_default = st.selectbox("Modelo padrão (Groq)", provider.available_models(), index=0)

        st.markdown("### O que gerar nesse dia")
        spec = {}
        cols = st.columns(3)
        for idx, ctype in enumerate(CONTENT_TYPES):
            with cols[idx % 3]:
                qty = st.number_input(ctype, 0, 30, 0, 1, key=f"spec_{ctype}")
                if qty:
                    spec[ctype] = int(qty)

        enabled = st.checkbox("Ativa", value=True)

        if st.button("💾 Salvar rotina", type="primary", use_container_width=True):
            if not spec:
                st.error("Defina pelo menos 1 item para gerar.")
            else:
                db.upsert_schedule(
                    client_id=current_client["id"],
                    weekday=int(weekday),
                    hour=int(hour),
                    minute=int(minute),
                    spec=spec,
                    provider_default="groq",
                    model_default=model_default,
                    enabled=1 if enabled else 0,
                )
                st.success("Rotina salva! (Recarregue se não aparecer na lista.)")

        st.divider()
        st.markdown("### Rotinas existentes")
        schedules = db.list_schedules(current_client["id"])
        if not schedules:
            st.info("Nenhuma rotina cadastrada.")
        else:
            for s in schedules:
                with st.expander(f"#{s['id']} — {WEEKDAYS[s['weekday']]} {s['hour']:02d}:{s['minute']:02d} — {'Ativa' if s['enabled'] else 'Pausada'}", expanded=False):
                    st.json(s.get("spec",{}))
                    if st.button("🗑️ Excluir", key=f"del_{s['id']}"):
                        db.delete_schedule(s["id"], current_client["id"])
                        st.warning("Excluída. Recarregue (F5).")

    with tab2:
        st.markdown("### Executar rotinas")
        schedules = [s for s in db.list_schedules(current_client["id"]) if int(s.get("enabled",1))==1]
        if not schedules:
            st.info("Sem rotinas ativas.")
            st.stop()

        now = datetime.now()
        today_wd = now.weekday()  # 0=Mon
        st.write(f"Hoje: **{WEEKDAYS[today_wd]}** ({now.strftime('%Y-%m-%d %H:%M')})")

        run_today = st.checkbox("Executar apenas as de hoje", value=True)
        candidates = [s for s in schedules if (s["weekday"]==today_wd or not run_today)]

        sel = st.selectbox(
            "Escolha uma rotina para executar",
            options=candidates,
            format_func=lambda s: f"#{s['id']} — {WEEKDAYS[s['weekday']]} {s['hour']:02d}:{s['minute']:02d} ({json.dumps(s['spec'], ensure_ascii=False)})",
        )

        model = st.selectbox("Modelo para execução", provider.available_models(), index=0, key="run_model")
        temperature = st.slider("Temperatura", 0.0, 1.2, 0.35, 0.05, key="run_temp")

        if st.button("🚀 Executar rotina agora", type="primary", use_container_width=True):
            with st.spinner("Gerando itens..."):
                created = 0
                for ctype, qty in (sel.get("spec") or {}).items():
                    instr = build_instruction(current_client, ctype, n=int(qty), extra="")
                    sys_prompt = get_system_prompt(current_client)
                    output = run_task(
                        provider=provider,
                        model=model,
                        client=current_client,
                        instruction=instr,
                        input_text="",
                        temperature=float(temperature),
                        system_prompt=sys_prompt,
                    )
                    title = f"Rotina {WEEKDAYS[sel['weekday']]} — {ctype}"
                    save_generation(
                        client_id=current_client["id"],
                        ctype_=ctype,
                        title=title,
                        prompt_used=instr,
                        output_text=output,
                        model=model,
                        input_source="manual",
                        input_ref=None,
                        tags=f"rotina:{sel['id']}",
                    )
                    created += 1
            st.success(f"Executado! Itens gerados e salvos: {created} (1 por tipo).")

        st.caption("Obs.: por padrão, cada tipo gera um bloco com {n} itens (ex.: 4 copies dentro de um output).")

elif page == "Histórico":
    st.header("Histórico / Biblioteca")
    require_client(current_client)

    colA, colB, colC = st.columns([2,2,2])
    with colA:
        ctype = st.selectbox("Filtrar por tipo", ["Todos"] + CONTENT_TYPES, index=0)
    with colB:
        q = st.text_input("Buscar no título/tags", value="")
    with colC:
        limit = st.number_input("Limite", 10, 500, 50, 10)

    items = db.list_content_items(current_client["id"], limit=int(limit))
    if ctype != "Todos":
        items = [i for i in items if i.get("type")==ctype]
    if q.strip():
        qq=q.lower().strip()
        items = [i for i in items if qq in (i.get("title","").lower()+ " " + (i.get("tags","").lower()))]

    if not items:
        st.info("Nada encontrado.")
        st.stop()

    for it in items:
        head = f"[{it['type']}] {it.get('title','(sem título)')} — {it['created_at']}"
        with st.expander(head, expanded=False):
            st.caption(f"Modelo: {it['model']} | Status: {it.get('status','draft')} | Tags: {it.get('tags','')}")
            if it.get("input_source")=="transcription" and it.get("input_ref"):
                tr = db.get_transcription(int(it["input_ref"]))
                if tr:
                    st.caption(f"Vinculado à transcrição #{tr['id']} (vídeo #{tr['video_id']})")
            st.markdown("**Prompt usado**")
            st.code(it.get("prompt_used",""))
            st.markdown("**Resultado**")
            st.markdown(it.get("output_text",""))
