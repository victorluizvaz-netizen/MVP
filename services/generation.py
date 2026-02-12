import json
from typing import Tuple, Dict

CONTENT_TYPES = ["Ideias", "Copy Reels", "Carrossel", "Campanha", "Stories", "Roteiro"]

DEFAULT_TEMPLATES = {
    "Ideias": "Gere {n} ideias de vídeos para Instagram (Reels). Para cada ideia: Título, Gancho, Roteiro (5 bullets), CTA.",
    "Copy Reels": "Crie {n} copies para Reels. Formato: Gancho, Desenvolvimento (4–7 linhas), CTA.",
    "Carrossel": "Crie {n} carrosseis. Formato: Slide 1 título, Slides 2–7 conteúdo, Slide final CTA.",
    "Campanha": "Crie {n} ideias de campanha com: Objetivo, Oferta/ângulo, Público, Mensagem, 3 criativos, CTA.",
    "Stories": "Crie {n} sequências de Stories (5 telas) com gancho, dor, prova, solução, CTA.",
    "Roteiro": "Crie {n} roteiros Reels (30–60s): abertura, desenvolvimento, fechamento+CTA, observações de gravação.",
}

def build_client_context(client: dict) -> str:
    parts = []
    def add(label, val):
        if val and str(val).strip():
            parts.append(f"{label}: {str(val).strip()}")
    add("Cliente", client.get("name"))
    add("Descrição", client.get("description"))
    add("Tom de voz", client.get("brand_voice"))
    add("Público", client.get("audience"))
    add("Oferta", client.get("offer"))
    add("Diferenciais", client.get("differentiators"))
    add("Objeções", client.get("objections"))
    add("Restrições", client.get("constraints"))
    add("CTA", client.get("cta"))
    return "\n".join(parts).strip()

def get_client_templates(client: dict) -> Dict[str, str]:
    tj = client.get("templates_json") or "{}"
    try:
        data = json.loads(tj)
        if isinstance(data, dict):
            return {k: str(v) for k,v in data.items() if v}
        return {}
    except Exception:
        return {}

def system_prompt(client: dict) -> str:
    if (client.get("system_prompt") or "").strip():
        return client["system_prompt"].strip()
    return ("Você é um estrategista e copywriter sênior focado em Instagram. "
            "Entregue respostas objetivas e aplicáveis. Escreva em pt-BR.")

def build_prompt(client: dict, content_type: str, n: int, extra: str = "", transcript: str = "") -> Tuple[str, str]:
    ctx = build_client_context(client)
    templates = get_client_templates(client)
    template = (templates.get(content_type) or DEFAULT_TEMPLATES[content_type]).strip()
    task = template.format(n=n)
    user_parts = [f"CONTEXTO DO CLIENTE:\n{ctx}"]
    if transcript.strip():
        user_parts.append(f"TRANSCRIÇÃO (base):\n{transcript.strip()}")
    if extra.strip():
        user_parts.append(f"INFORMAÇÕES ADICIONAIS:\n{extra.strip()}")
    user_parts.append(f"TAREFA:\n{task}")
    user_prompt = "\n\n---\n\n".join(user_parts)
    sys = system_prompt(client)
    prompt_used = f"SYSTEM:\n{sys}\n\nUSER:\n{user_prompt}"
    return sys, user_prompt, prompt_used
