import json
import streamlit as st
from db import fetchall, fetchone, exec_sql, now_utc
from auth import audit
from pages.common import need_role
from services.generation import CONTENT_TYPES

def render(workspace_id: int):
    st.header("Clientes")
    need_role("editor", "Somente owner/editor pode criar/editar clientes.")

    clients = fetchall("SELECT * FROM clients WHERE workspace_id=? ORDER BY name COLLATE NOCASE", (workspace_id,))
    left, right = st.columns([1,2])

    with left:
        st.subheader("Lista")
        if clients:
            sel = st.selectbox("Selecionar", clients, format_func=lambda c: f"#{c['id']} - {c['name']}", key="clients_sel")
            client_id = int(sel["id"])
        else:
            client_id = None
            st.info("Nenhum cliente.")
        st.divider()
        if st.button("➕ Novo cliente", type="primary"):
            st.session_state["clients_sel"] = None
            st.session_state["clients_new"] = True
            st.rerun()

    with right:
        is_new = st.session_state.get("clients_new", False) or (client_id is None)
        if is_new:
            st.subheader("Cadastrar cliente")
            name = st.text_input("Nome", value="")
            description = st.text_area("Descrição", height=110)
            c1, c2 = st.columns(2)
            with c1:
                brand_voice = st.text_area("Tom de voz", height=80)
                audience = st.text_area("Público", height=80)
                offer = st.text_area("Oferta", height=80)
            with c2:
                differentiators = st.text_area("Diferenciais", height=80)
                objections = st.text_area("Objeções", height=80)
                constraints = st.text_area("Restrições", height=80)
            cta = st.text_input("CTA")
            system_prompt = st.text_area("System prompt (opcional)", height=90)

            full = {k:"" for k in CONTENT_TYPES}
            templates_json = st.text_area("Templates JSON (opcional)", value=json.dumps(full, ensure_ascii=False, indent=2), height=180)

            if st.button("Salvar", type="primary"):
                if not name.strip():
                    st.error("Nome obrigatório.")
                    return
                try:
                    raw = json.loads(templates_json or "{}")
                    clean = {k:(raw.get(k) or "").strip() for k in CONTENT_TYPES if (raw.get(k) or "").strip()}
                    tj = json.dumps(clean, ensure_ascii=False)
                except Exception:
                    st.error("Templates JSON inválido.")
                    return

                exec_sql("""
                    INSERT INTO clients (workspace_id, name, description, system_prompt, brand_voice, audience, offer,
                                        differentiators, objections, constraints, cta, templates_json, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (workspace_id, name.strip(), description, system_prompt, brand_voice, audience, offer,
                        differentiators, objections, constraints, cta, tj, now_utc(), now_utc()))
                new_id = fetchone("SELECT id FROM clients WHERE workspace_id=? ORDER BY id DESC LIMIT 1", (workspace_id,))["id"]
                audit("client_created", {"client_id": new_id, "name": name.strip()}, workspace_id=workspace_id)
                st.session_state["clients_new"] = False
                st.success("Cliente criado.")
                st.rerun()
        else:
            client = fetchone("SELECT * FROM clients WHERE workspace_id=? AND id=?", (workspace_id, client_id))
            if not client:
                st.error("Cliente não encontrado.")
                return
            st.subheader(f"Editar: {client['name']}")
            name = st.text_input("Nome", value=client.get("name") or "")
            description = st.text_area("Descrição", value=client.get("description") or "", height=110)
            c1, c2 = st.columns(2)
            with c1:
                brand_voice = st.text_area("Tom de voz", value=client.get("brand_voice") or "", height=80)
                audience = st.text_area("Público", value=client.get("audience") or "", height=80)
                offer = st.text_area("Oferta", value=client.get("offer") or "", height=80)
            with c2:
                differentiators = st.text_area("Diferenciais", value=client.get("differentiators") or "", height=80)
                objections = st.text_area("Objeções", value=client.get("objections") or "", height=80)
                constraints = st.text_area("Restrições", value=client.get("constraints") or "", height=80)
            cta = st.text_input("CTA", value=client.get("cta") or "")
            system_prompt = st.text_area("System prompt (opcional)", value=client.get("system_prompt") or "", height=90)

            # expand templates for editing
            try:
                existing = json.loads(client.get("templates_json") or "{}")
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
            full = {k: existing.get(k,"") for k in CONTENT_TYPES}
            templates_json = st.text_area("Templates JSON (opcional)", value=json.dumps(full, ensure_ascii=False, indent=2), height=180)

            if st.button("Atualizar", type="primary"):
                if not name.strip():
                    st.error("Nome obrigatório.")
                    return
                try:
                    raw = json.loads(templates_json or "{}")
                    clean = {k:(raw.get(k) or "").strip() for k in CONTENT_TYPES if (raw.get(k) or "").strip()}
                    tj = json.dumps(clean, ensure_ascii=False)
                except Exception:
                    st.error("Templates JSON inválido.")
                    return

                exec_sql("""
                    UPDATE clients SET name=?, description=?, system_prompt=?, brand_voice=?, audience=?, offer=?,
                        differentiators=?, objections=?, constraints=?, cta=?, templates_json=?, updated_at=?
                    WHERE workspace_id=? AND id=?
                """, (name.strip(), description, system_prompt, brand_voice, audience, offer,
                        differentiators, objections, constraints, cta, tj, now_utc(), workspace_id, client_id))
                audit("client_updated", {"client_id": client_id, "name": name.strip()}, workspace_id=workspace_id)
                st.success("Atualizado.")
                st.rerun()
