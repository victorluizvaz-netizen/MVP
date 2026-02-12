
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

st.set_page_config(page_title="Content OS (Whisper + Groq)", layout="wide")

# ---------- session state defaults ----------
for _k, _v in {
    "user": None,
    "workspace_id": None,
    "workspace_name": None,
    "workspace_role": None,
    "last_generation": None,
}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ---------- init ----------
db.init_db()
# Create initial admin if configured via env vars
try:
    db.bootstrap_admin_from_env()
except Exception:
    pass


# ---------- providers ----------
providers = {}
try:
    providers["groq"] = GroqProvider.from_streamlit_secrets()
except Exception as e:
    providers["groq_error"] = str(e)

def provider_ready():
    if "groq" not in providers:
        st.error("Groq indisponível: " + str(providers.get("groq_error", "sem detalhes")))

    return providers["groq"]

# ---------- auth/session helpers ----------
def logout():
    for k in ["user", "workspace_id", "workspace_name"]:
        st.session_state.pop(k, None)
    st.rerun()

def require_login():
    if not st.session_state.get("user"):
        login_ui()
        st.stop()


def require_workspace():
    if not st.session_state.get("workspace_id"):
        st.warning("Selecione um painel (workspace) na sidebar.")
        st.stop()


def login_ui():
    st.title("Content OS")
    st.caption("Faça login para acessar seus painéis (workspaces). Cada painel tem seus próprios clientes, vídeos e histórico.")

    tab1, tab2, tab3, tab4 = st.tabs(["Entrar", "Criar conta", "Aceitar convite", "Redefinir senha"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Senha", type="password", key="login_pass")
        if st.button("Entrar", type="primary", use_container_width=True):
            u = db.verify_user(email=email, password=password)
            if not u:
                st.error("Email ou senha inválidos.")
            elif int(u.get("is_active", 1)) == 0:
                st.warning("Sua conta ainda não foi aprovada pelo administrador.")
            else:
                st.session_state["user"] = u
                try:
                    db.log_event(int(u["id"]), None, "login", "user", int(u["id"]), {})
                except Exception:
                    pass
                st.success("Login ok!")
                st.rerun()

    
    with tab2:
        st.write("As contas passam por **aprovação do administrador** antes de liberar o acesso.")
        name = st.text_input("Nome (opcional)", key="signup_name")
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Senha", type="password", key="signup_pass")
        ws_name = st.text_input("Nome do seu painel (workspace)", value="Meu Painel", key="signup_ws")
        if st.button("Solicitar criação de conta", type="primary", use_container_width=True):
            try:
                # Se não existe admin ainda, o primeiro usuário vira admin e já fica ativo (evita lockout)
                if db.count_admins() == 0:
                    uid = db.create_user(email=email, password=password, name=name, is_admin=True, is_active=True, requested_workspace_name=ws_name)
                    wid = db.create_workspace(ws_name)
                    db.add_membership(uid, wid, role="owner")
                    try:
                        db.log_event(int(uid), int(wid), "bootstrap_admin_created", "workspace", int(wid), {"email": email.lower().strip()})
                    except Exception:
                        pass
                    st.session_state["user"] = {"id": uid, "email": email.lower().strip(), "name": name.strip(), "is_admin": 1, "is_active": 1}
                    st.session_state["workspace_id"] = wid
                    st.session_state["workspace_name"] = ws_name.strip()
                    st.success("Admin inicial criado e painel criado!")
                    st.rerun()
                else:
                    uid = db.create_user(email=email, password=password, name=name, is_admin=False, is_active=False, requested_workspace_name=ws_name)
                    try:
                        db.log_event(None, None, "signup_requested", "user", int(uid), {"email": email.lower().strip(), "workspace": ws_name})
                    except Exception:
                        pass
                    st.success("Solicitação enviada! Aguarde a aprovação do administrador.")
            except Exception as e:
                st.error(f"Não foi possível solicitar a conta: {e}")

    with tab3:
        st.write("Cole aqui o **token de convite** (gerado no painel do dono).")
        token = st.text_input("Token de convite", key="invite_token")
        if st.button("Aceitar convite (precisa estar logado)", use_container_width=True):
            if not st.session_state.get("user"):
                st.error("Faça login primeiro na aba **Entrar**.")
            else:
                wid = db.accept_invite(token=token, user_id=int(st.session_state["user"]["id"]))
                if not wid:
                    st.error("Convite inválido, expirado, restrito a outro email ou já utilizado.")
                else:
                    try:
                        db.log_event(int(st.session_state["user"]["id"]), int(wid), "invite_accepted", "workspace", int(wid), {})
                    except Exception:
                        pass
                    st.success("Convite aceito! Selecione o painel na sidebar.")
                    st.rerun()


    with tab4:
        st.write("Se você recebeu um **token de redefinição de senha**, cole abaixo e crie uma nova senha.")
        token = st.text_input("Token de redefinição", key="reset_token")
        new_pass = st.text_input("Nova senha", type="password", key="reset_newpass")
        if st.button("Redefinir senha", type="primary", use_container_width=True, key="do_reset"):
            ok = db.reset_password_with_token(token=token, new_password=new_pass)
            if ok:
                st.success("Senha atualizada! Agora você já pode entrar na aba **Entrar**.")
            else:
                st.error("Token inválido, expirado ou já utilizado.")

def workspace_sidebar():
    user = st.session_state.get("user")
    if not user:
        return

    wss = db.list_user_workspaces(int(user["id"]))

    st.sidebar.markdown("### Painel (Workspace)")
    if not wss:
        st.sidebar.warning("Você ainda não tem nenhum painel.")
        new_name = st.sidebar.text_input("Nome do novo painel", value="Novo Painel")
        if st.sidebar.button("Criar painel"):
            wid = db.create_workspace(new_name)
            db.add_membership(int(user["id"]), wid, role="owner")
            try:
                db.log_event(int(user["id"]), int(wid), "workspace_created", "workspace", int(wid), {"name": new_name.strip()})
            except Exception:
                pass
            st.session_state["workspace_id"] = wid
            st.session_state["workspace_name"] = new_name.strip()
            st.rerun()
        return

    # pick current
    current_id = st.session_state.get("workspace_id")
    idx = 0
    if current_id:
        for i, w in enumerate(wss):
            if int(w["id"]) == int(current_id):
                idx = i
                break

    sel_ws = st.sidebar.selectbox(
        "Escolha",
        wss,
        index=idx,
        format_func=lambda w: f"#{w['id']} - {w['name']} ({w['role']})",
    )

    wid = int(sel_ws["id"])
    wname = sel_ws["name"].strip()
    st.session_state["workspace_id"] = wid
    st.session_state["workspace_name"] = wname

    mem = db.get_membership(int(user["id"]), wid)
    role = (mem or {}).get("role", "viewer")
    st.session_state["workspace_role"] = role

    if role == "owner":
        with st.sidebar.expander("👥 Convidar pessoas", expanded=False):
            invited_email = st.text_input("Email (opcional)", key="inv_email")
            inv_role = st.selectbox("Papel", ["viewer", "editor", "owner"], index=1, key="inv_role")
            exp_days = st.number_input("Expira em (dias)", min_value=1, max_value=90, value=7, step=1, key="inv_exp")
            if st.button("Gerar convite", use_container_width=True, key="gen_invite"):
                token = db.create_invite(
                    workspace_id=wid,
                    created_by=int(user["id"]),
                    role=inv_role,
                    invited_email=(invited_email.strip().lower() if invited_email else None),
                    expires_in_days=int(exp_days),
                )
                try:
                    db.log_event(int(user["id"]), wid, "invite_created", "invite", None, {"role": inv_role, "expires_days": int(exp_days), "email": invited_email or None})
                except Exception:
                    pass
                st.success("Convite gerado. Copie e envie o token abaixo:")
                st.code(token, language="text")




def set_last_generation(workspace_id: int, client_id: int, payload: dict):
    st.session_state[_gen_key(workspace_id, client_id)] = payload

def get_last_generation(workspace_id: int, client_id: int) -> dict:
    return st.session_state.get(_gen_key(workspace_id, client_id), {})

def save_generation(workspace_id, client_id, ctype, title, prompt_used, output_text, model, input_source="manual", input_ref=None, tags=""):
    cid = db.add_content_item(
        workspace_id=workspace_id,
        client_id=client_id,
        type=ctype,
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
    try:
        actor = int(st.session_state.get("user", {}).get("id"))
    except Exception:
        actor = None
    try:
        db.log_event(actor, int(workspace_id), "content_saved", "content_item", int(cid), {"type": ctype, "client_id": int(client_id), "tags": tags or ""})
    except Exception:
        pass
    return cid


# ---------- constants ----------
CONTENT_TYPES = ["Ideias", "Copy Reels", "Carrossel", "Campanha", "Stories", "Roteiro"]
WEEKDAYS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

ROLE_ORDER = {"viewer": 0, "editor": 1, "owner": 2}

def current_role() -> str:
    return st.session_state.get("workspace_role", "viewer")

def can_edit() -> bool:
    return ROLE_ORDER.get(current_role(), 0) >= ROLE_ORDER["editor"]

def is_owner() -> bool:
    return current_role() == "owner"

def require_editor():
    if not can_edit():
        st.warning("Seu papel neste painel é **viewer**. Você pode visualizar, mas não pode editar/gerar. Peça ao dono para te promover para **editor**.")


def require_owner():
    if not is_owner():
        st.warning("Apenas o **owner** pode gerenciar convites e permissões deste painel.")


# ---------- auth gate ----------
if not st.session_state.get("user"):
    login_ui()
    st.stop()


workspace_sidebar()
require_workspace()

WORKSPACE_ID = int(st.session_state["workspace_id"])

# ---------- sidebar navigation ----------
pages = ["Dashboard", "Clientes", "Gerador", "Vídeos", "Rotinas", "Histórico"]
if is_owner():
    pages.append("Auditoria")
if int(st.session_state.get("user", {}).get("is_admin", 0)) == 1:
    pages.insert(0, "Admin")
page = st.sidebar.radio("Navegação", pages, index=0)

# ---------- load clients ----------
clients = db.list_clients(WORKSPACE_ID)
client_names = ["— selecione —"] + [c["name"] for c in clients]
name_to_id = {c["name"]: c["id"] for c in clients}

sel_client_name = st.sidebar.selectbox("Cliente", client_names, index=0)
current_client = None
if sel_client_name != "— selecione —":
    current_client = db.get_client(WORKSPACE_ID, int(name_to_id[sel_client_name]))

def require_client(client):
    if not client:
        st.warning("Selecione um cliente na sidebar.")



# ---------- pages ----------

if page == "Admin":
    st.header("Administração")
    user = st.session_state.get("user", {})
    if int(user.get("is_admin", 0)) != 1:
        st.error("Acesso negado.")
        st.stop()

    # ---- pending approvals ----
    st.subheader("Solicitações pendentes")
    pending = db.list_pending_users()
    if not pending:
        st.info("Nenhuma conta pendente.")
    else:
        for u in pending:
            c1, c2, c3 = st.columns([4, 1, 1])
            with c1:
                st.write(f"**{u['email']}**  — {u.get('name','')}")
                st.caption(
                    f"Workspace solicitado: {u.get('requested_workspace_name','') or 'Meu Painel'} • Criado em: {u.get('created_at','')}"
                )
            with c2:
                if st.button("Aprovar", key=f"appr_{u['id']}", type="primary"):
                    wid = db.approve_user(int(u["id"]))
                    try:
                        db.log_event(int(user["id"]), int(wid), "user_approved", "user", int(u["id"]), {"workspace_id": int(wid)})
                    except Exception:
                        pass
                    st.success(f"Usuário aprovado! Workspace #{wid} criado.")
                    st.rerun()
            with c3:
                if st.button("Rejeitar", key=f"rej_{u['id']}"):
                    db.delete_user(int(u["id"]))
                    try:
                        db.log_event(int(user["id"]), None, "user_rejected", "user", int(u["id"]), {})
                    except Exception:
                        pass
                    st.warning("Usuário removido.")
                    st.rerun()

    st.divider()

    # ---- users ----
    st.subheader("Usuários")
    st.caption("Você pode ativar/desativar, definir admin e gerar token de redefinição de senha (60 min).")
    users = db.list_users()
    for u in users:
        colA, colB, colC = st.columns([5, 2, 3])
        with colA:
            flags = []
            if int(u.get("is_admin", 0)) == 1:
                flags.append("admin")
            if int(u.get("is_active", 0)) == 0:
                flags.append("pendente")
            st.write(f"**{u['email']}** ({', '.join(flags) if flags else 'ok'})")
            st.caption(f"ID: {u['id']} • Criado: {u.get('created_at','')} • Aprovado: {u.get('approved_at','') or '—'}")

        with colB:
            if int(u.get("is_active", 0)) == 1:
                if st.button("Desativar", key=f"dis_{u['id']}"):
                    db.set_user_active(int(u["id"]), False)
                    try:
                        db.log_event(int(user["id"]), None, "user_deactivated", "user", int(u["id"]), {})
                    except Exception:
                        pass
                    st.rerun()
            else:
                if st.button("Ativar", key=f"act_{u['id']}"):
                    db.set_user_active(int(u["id"]), True)
                    try:
                        db.log_event(int(user["id"]), None, "user_activated", "user", int(u["id"]), {})
                    except Exception:
                        pass
                    st.rerun()

        with colC:
            if int(u["id"]) != int(user.get("id")):
                make_admin = st.checkbox("Admin", value=int(u.get("is_admin", 0)) == 1, key=f"isadm_{u['id']}")
                if st.button("Salvar admin", key=f"saveadm_{u['id']}"):
                    db.promote_to_admin(int(u["id"]), bool(make_admin))
                    try:
                        db.log_event(int(user["id"]), None, "admin_flag_updated", "user", int(u["id"]), {"is_admin": bool(make_admin)})
                    except Exception:
                        pass
                    st.rerun()

            if st.button("Gerar token de senha", key=f"pwreset_{u['id']}"):
                token = db.create_password_reset_for_user(int(u["id"]), expires_minutes=60, created_by_admin=1)
                try:
                    db.log_event(int(user["id"]), None, "password_reset_token_created", "user", int(u["id"]), {})
                except Exception:
                    pass
                st.success("Token gerado (válido por 60 min):")
                st.code(token)

    st.divider()
    st.subheader("Tokens de senha ativos")
    active_tokens = db.list_password_resets(active_only=True)
    if not active_tokens:
        st.info("Nenhum token ativo.")
    else:
        for t in active_tokens[:30]:
            st.write(f"**{t.get('email','')}** — expira em: {t.get('expires_at','')}")
            st.code(t.get("token",""))

    st.divider()
    st.subheader("Auditoria (global)")
    st.caption("Últimos 200 eventos do sistema.")
    logs = db.list_audit(workspace_id=None, limit=200)
    for ev in logs:
        meta = ev.get("meta", {})
        st.write(f"**{ev.get('created_at','')}** — `{ev.get('action','')}` — {ev.get('actor_email','—')}")
        if ev.get("workspace_id"):
            st.caption(f"Workspace: {ev.get('workspace_id')} • {ev.get('entity_type','')} #{ev.get('entity_id','')}")
        if meta:
            st.json(meta, expanded=False)

    st.stop()



if page == "Dashboard":
    st.header("Dashboard")
    st.caption(f"Workspace: **{st.session_state.get('workspace_name','')}**")

    if current_client:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Vídeos", len(db.list_videos(WORKSPACE_ID, current_client["id"])))
        with col2:
            st.metric("Transcrições", sum(len(db.list_transcriptions_for_video(WORKSPACE_ID, v["id"])) for v in db.list_videos(WORKSPACE_ID, current_client["id"])))
        with col3:
            st.metric("Conteúdos", len(db.list_content_items(WORKSPACE_ID, current_client["id"], limit=9999)))

        st.divider()
        st.subheader("Últimos conteúdos")
        items = db.list_content_items(WORKSPACE_ID, current_client["id"], limit=20)
        if not items:
            st.info("Nada ainda. Gere algo no menu **Gerador**.")
        else:
            for it in items[:10]:
                with st.expander(f"[{it['type']}] {it.get('title','(sem título)')} — {it['created_at']}", expanded=False):
                    st.caption(f"Modelo: {it['model']} | Tags: {it.get('tags','')}")
                    st.markdown(it.get("output_text",""))

    else:
        st.info("Selecione um cliente para ver métricas rápidas e os últimos conteúdos.")

elif page == "Clientes":
    st.header("Clientes")
    st.caption("Cada cliente fica dentro do seu painel (workspace). Outros usuários só veem se forem convidados.")

    tab1, tab2 = st.tabs(["Cadastrar/Editar", "Lista"])
    with tab1:
        cid = None
        if current_client:
            cid = current_client["id"]

        name = st.text_input("Nome do cliente", value=current_client["name"] if current_client else "")
        desc = st.text_area("Descrição (editável)", value=current_client.get("description","") if current_client else "", height=120)

        profile = (current_client.get("profile") if current_client else {}) or {}

        colA, colB = st.columns(2)
        with colA:
            nicho = st.text_input("Nicho", value=profile.get("nicho",""))
            publico = st.text_input("Público", value=profile.get("publico",""))
            tom = st.text_input("Tom de voz", value=profile.get("tom_de_voz",""))
            cta = st.text_input("CTA padrão", value=profile.get("cta",""))
        with colB:
            oferta = st.text_area("Oferta", value=profile.get("oferta",""), height=80)
            diferenciais = st.text_area("Diferenciais", value=profile.get("diferenciais",""), height=80)
            restricoes = st.text_area("Restrições (não usar / não prometer)", value=profile.get("restricoes",""), height=80)

        st.markdown("### Preset do cliente (opcional)")
        system_prompt = st.text_area("System prompt custom (se vazio, usa o padrão)", value=profile.get("system_prompt",""), height=100)

        st.markdown("### Templates por tipo (opcional)")
        st.caption("Se você preencher aqui, o sistema usa seu template no lugar do padrão para este cliente.")
        prefs = profile.get("format_prefs") or {}
        prefs_out = {}
        for ctype in CONTENT_TYPES:
            prefs_out[ctype] = st.text_area(
                f"Template: {ctype}",
                value=prefs.get(ctype, DEFAULT_TEMPLATES.get(ctype,"")),
                height=90,
                key=f"tpl_{ctype}"
            )

        new_profile = {
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
                        db.upsert_client(name=name, description=desc, profile=new_profile, workspace_id=WORKSPACE_ID, client_id=cid)
                        st.success("Salvo! Recarregue (F5) para atualizar o seletor de cliente.")
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
        with colS2:
            if cid is not None and st.button("🗑️ Excluir cliente", use_container_width=True):
                db.delete_client(WORKSPACE_ID, cid)
                st.warning("Cliente excluído. Recarregue (F5).")

    with tab2:
        st.subheader("Clientes cadastrados")
        st.dataframe(db.list_clients(WORKSPACE_ID), use_container_width=True)

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

    extra = st.text_area("Contexto extra (opcional)", height=100, placeholder="Ex.: foco em captação no WhatsApp, mencionar dor X, etc.")
    instruction_preview = build_instruction(current_client, content_type, n=int(n), extra=extra)
    with st.expander("Ver instrução (preview)", expanded=False):
        st.code(instruction_preview)

    st.markdown("### Fonte")
    mode = st.radio("Fonte de conteúdo", ["Manual", "Usar transcrição de um vídeo"], horizontal=True)

    transcription_id = None
    input_text = ""
    if mode == "Usar transcrição de um vídeo":
        vids = db.list_videos(WORKSPACE_ID, current_client["id"])
        if not vids:
            st.warning("Este cliente ainda não tem vídeos.")
        else:
            sel_v = st.selectbox(
                "Escolha um vídeo",
                vids,
                index=0,
                format_func=lambda v: f"#{v['id']} - {v['filename']} ({v.get('created_at','')})",
            )
            vid_id = int(sel_v["id"])
            trans = db.list_transcriptions_for_video(WORKSPACE_ID, vid_id)
            if not trans:
                st.warning("Vídeo ainda não foi transcrito. Vá em **Vídeos** e transcreva.")
            else:
                tlabel = [f"Transcrição #{t['id']} ({t['created_at']})" for t in trans]
                sel_t = st.selectbox("Escolha a transcrição", tlabel, index=0)
                transcription_id = int(sel_t.split("#")[1].split()[0])
                t = db.get_transcription(WORKSPACE_ID, transcription_id)
                input_text = (t or {}).get("text","")
                with st.expander("Ver transcrição", expanded=False):
                    st.text_area("Transcrição", value=input_text, height=200)

    if st.button("✨ Gerar agora", type="primary", use_container_width=True):
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
        payload = {
            "content_type": content_type,
            "instruction": instruction_preview,
            "output": output,
            "model": model,
            "transcription_id": transcription_id,
            "created_at": datetime.now().isoformat(),
        }
        set_last_generation(WORKSPACE_ID, current_client["id"], payload)
        st.success("Pronto!")
        st.rerun()

    last = get_last_generation(WORKSPACE_ID, current_client["id"])
    if last:
        st.markdown("### Última geração")
        st.caption(f"Tipo: {last.get('content_type')} | Modelo: {last.get('model')} | {last.get('created_at','')}")
        st.markdown(last.get("output",""))

        with st.expander("Salvar no histórico", expanded=True):
            title_default = f"{last.get('content_type')} — {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            title = st.text_input("Título (opcional)", value=title_default, key="hist_title")
            tags = st.text_input("Tags (opcional)", value="", key="hist_tags")
            if st.button("💾 Salvar no histórico", use_container_width=True, key="hist_save"):
                save_generation(
                    workspace_id=WORKSPACE_ID,
                    client_id=current_client["id"],
                    ctype=last.get("content_type"),
                    title=title,
                    prompt_used=last.get("instruction",""),
                    output_text=last.get("output",""),
                    model=last.get("model",""),
                    input_source="transcription" if last.get("transcription_id") else "manual",
                    input_ref=last.get("transcription_id"),
                    tags=tags,
                )
                st.success("Salvo!")
    else:
        st.info("Nenhuma geração ainda nesta sessão para este cliente. Clique em **Gerar agora**.")

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
        client_dir = VIDEOS_DIR / f"workspace_{WORKSPACE_ID}" / f"client_{current_client['id']}"
        client_dir.mkdir(parents=True, exist_ok=True)
        filepath = client_dir / up.name
        filepath.write_bytes(up.getvalue())
        vid_id = db.add_video(WORKSPACE_ID, current_client["id"], up.name, filepath.as_posix())

        with st.spinner("Transcrevendo com Whisper..."):
            text, segments = transcribe_video_bytes(up.getvalue(), whisper_model=whisper_model, language=None if language=="auto" else language)
        t_id = db.add_transcription(workspace_id=WORKSPACE_ID, video_id=vid_id, text=text, segments=segments, engine="whisper")
        st.success(f"Transcrição salva! (Vídeo #{vid_id} / Transcrição #{t_id})")

    st.divider()

    vids = db.list_videos(WORKSPACE_ID, current_client["id"])
    if not vids:
        st.info("Nenhum vídeo cadastrado ainda.")
return

    left, right = st.columns([1,2])
    with left:
        st.markdown("### Biblioteca")
        sel_v = st.radio(
            "Selecione um vídeo",
            vids,
            index=0,
            format_func=lambda v: f"#{v['id']} - {v['filename']}",
        )
        video_id = int(sel_v["id"])

    v = db.get_video(WORKSPACE_ID, video_id)
    trans = db.list_transcriptions_for_video(WORKSPACE_ID, video_id)

    with right:
        st.markdown(f"### Vídeo #{video_id}")
        st.caption(v.get("filepath",""))
        if not trans:
            st.warning("Ainda sem transcrição.")


        tlabel = [f"Transcrição #{t['id']} ({t['created_at']})" for t in trans]
        sel_t = st.selectbox("Escolha a transcrição", tlabel, index=0)
        tid = int(sel_t.split("#")[1].split()[0])
        tr = db.get_transcription(WORKSPACE_ID, tid)

        with st.expander("Ver transcrição", expanded=False):
            st.text_area("Texto", value=(tr or {}).get("text",""), height=220)

        st.markdown("### Gerar a partir desta transcrição (salva automático)")
        ctype = st.selectbox("Tipo de conteúdo", CONTENT_TYPES, index=1, key="video_ctype")
        model = st.selectbox("Modelo (Groq)", provider.available_models(), index=0, key="video_model")
        n = st.number_input("Qtd", 1, 20, 3, 1, key="video_n")
        temperature = st.slider("Temperatura", 0.0, 1.2, 0.35, 0.05, key="video_temp")
        extra = st.text_area("Contexto extra (opcional)", height=80, key="video_extra")

        if st.button("⚡ Gerar e salvar", type="primary", use_container_width=True, key="video_run"):
            instr = build_instruction(current_client, ctype, n=int(n), extra=extra)
            sys_prompt = get_system_prompt(current_client)
            with st.spinner("Gerando..."):
                output = run_task(
                    provider=provider,
                    model=model,
                    client=current_client,
                    instruction=instr,
                    input_text=(tr or {}).get("text",""),
                    temperature=float(temperature),
                    system_prompt=sys_prompt,
                )
            title = f"{ctype} — vídeo #{video_id}"
            save_generation(
                workspace_id=WORKSPACE_ID,
                client_id=current_client["id"],
                ctype=ctype,
                title=title,
                prompt_used=instr,
                output_text=output,
                model=model,
                input_source="transcription",
                input_ref=tid,
                tags=f"video:{video_id}",
            )
            st.success("Salvo no histórico!")
            st.markdown(output)

        st.divider()
        st.markdown("### Conteúdos gerados deste vídeo")
        items = db.list_content_items_by_video(WORKSPACE_ID, current_client["id"], video_id, limit=50)
        if not items:
            st.info("Nenhum conteúdo salvo com tag deste vídeo ainda.")
        else:
            for it in items[:10]:
                with st.expander(f"[{it['type']}] {it.get('title','(sem título)')} — {it['created_at']}", expanded=False):
                    st.caption(f"Modelo: {it['model']} | Tags: {it.get('tags','')}")
                    st.markdown(it.get("output_text",""))

elif page == "Rotinas":
    st.header("Rotinas / Agenda (MVP)")
    require_client(current_client)
    provider = provider_ready()

    st.caption("Este MVP executa rotinas **com 1 clique**. Depois você pode automatizar via cron/scheduler.")

    st.subheader("Criar/Editar rotina")
    col1, col2, col3, col4 = st.columns([1,1,1,2])
    with col1:
        weekday = st.selectbox("Dia", list(range(7)), format_func=lambda x: WEEKDAYS[x], index=0)
    with col2:
        hour = st.number_input("Hora", 0, 23, 9, 1)
    with col3:
        minute = st.number_input("Min", 0, 59, 0, 5)
    with col4:
        model_default = st.selectbox("Modelo padrão (Groq)", provider.available_models(), index=0)

    st.markdown("### Quantidades por tipo")
    spec = {}
    cols = st.columns(3)
    for i,ctype in enumerate(CONTENT_TYPES):
        with cols[i % 3]:
            spec[ctype] = int(st.number_input(ctype, 0, 20, 0, 1, key=f"spec_{ctype}"))

    if st.button("💾 Salvar rotina", use_container_width=True, type="primary"):
        db.upsert_schedule(
            workspace_id=WORKSPACE_ID,
            client_id=current_client["id"],
            weekday=int(weekday),
            hour=int(hour),
            minute=int(minute),
            spec=spec,
            provider_default="groq",
            model_default=model_default,
            enabled=1,
        )
        st.success("Rotina salva!")

    st.divider()
    st.subheader("Rotinas cadastradas")
    schedules = db.list_schedules(WORKSPACE_ID, current_client["id"])
    if not schedules:
        st.info("Nenhuma rotina ainda.")


    for sel in schedules:
        with st.expander(f"#{sel['id']} — {WEEKDAYS[sel['weekday']]} {sel['hour']:02d}:{sel['minute']:02d} | {'ON' if sel['enabled'] else 'OFF'}", expanded=False):
            st.json(sel.get("spec", {}))

            if st.button(f"▶️ Rodar agora (rotina #{sel['id']})", key=f"run_sched_{sel['id']}", use_container_width=True):
                sys_prompt = get_system_prompt(current_client)
                created = 0
                with st.spinner("Gerando itens..."):
                    for ctype, qty in (sel.get("spec") or {}).items():
                        if not qty or int(qty) <= 0:
                            continue
                        instr = build_instruction(current_client, ctype, n=int(qty), extra="")
                        output = run_task(
                            provider=provider,
                            model=sel.get("model_default","llama-3.3-70b-versatile"),
                            client=current_client,
                            instruction=instr,
                            input_text="",
                            temperature=0.35,
                            system_prompt=sys_prompt,
                        )
                        title = f"Rotina {WEEKDAYS[sel['weekday']]} — {ctype}"
                        save_generation(
                            workspace_id=WORKSPACE_ID,
                            client_id=current_client["id"],
                            ctype=ctype,
                            title=title,
                            prompt_used=instr,
                            output_text=output,
                            model=sel.get("model_default","llama-3.3-70b-versatile"),
                            input_source="manual",
                            input_ref=None,
                            tags=f"rotina:{sel['id']}",
                        )
                        created += 1
                st.success(f"Rotina executada. Itens criados: {created}")
                st.caption("Cada tipo gera um bloco com {n} itens dentro do output.")

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

    items = db.list_content_items(WORKSPACE_ID, current_client["id"], limit=int(limit))
    if ctype != "Todos":
        items = [i for i in items if i.get("type")==ctype]
    if q.strip():
        qq=q.lower().strip()
        items = [i for i in items if qq in (i.get("title","").lower()+ " " + (i.get("tags","").lower()))]

    if not items:
        st.info("Nada encontrado.")


    for it in items:
        head = f"[{it['type']}] {it.get('title','(sem título)')} — {it['created_at']}"
        with st.expander(head, expanded=False):
            st.caption(f"Modelo: {it['model']} | Status: {it.get('status','draft')} | Tags: {it.get('tags','')}")
            if it.get("input_source")=="transcription" and it.get("input_ref"):
                tr = db.get_transcription(WORKSPACE_ID, int(it["input_ref"]))
                if tr:
                    st.caption(f"Vinculado à transcrição #{tr['id']} (vídeo #{tr['video_id']})")
            st.markdown("**Prompt usado**")
            st.code(it.get("prompt_used",""))
            st.markdown("**Resultado**")
            st.markdown(it.get("output_text",""))


elif page == "Auditoria":
    st.header("Auditoria do painel")
    require_owner()
    st.caption("Eventos recentes deste painel (workspace).")
    logs = db.list_audit(workspace_id=WORKSPACE_ID, limit=200)
    if not logs:
        st.info("Nenhum evento registrado ainda.")
    else:
        for ev in logs:
            meta = ev.get("meta", {})
            st.write(f"**{ev.get('created_at','')}** — `{ev.get('action','')}` — {ev.get('actor_email','—')}")
            if ev.get("entity_type") or ev.get("entity_id"):
                st.caption(f"{ev.get('entity_type','')} #{ev.get('entity_id','')}")
            if meta:
                st.json(meta, expanded=False)
