import json
from typing import Dict

CONTENT_TYPES = ["Ideias", "Copy Reels", "Carrossel", "Campanha", "Stories", "Roteiro"]

DEFAULT_TEMPLATES = {
    "Ideias": "Gere {n} ideias de Reels. Para cada: Título, Gancho, 5 bullets, CTA.",
    "Copy Reels": "Crie {n} copies para Reels: Gancho, Desenvolvimento, CTA.",
    "Carrossel": "Crie {n} carrosseis: Slide 1 título, Slides 2-7 conteúdo, slide final CTA.",
    "Campanha": "Crie {n} campanhas: objetivo, ângulo, público, mensagem, 3 criativos, CTA.",
    "Stories": "Crie {n} sequências de stories (5 telas) com textos curtos.",
    "Roteiro": "Crie {n} roteiros completos para Reels (30–60s).",
}

def client_context(client: dict) -> str:
    parts = [f"Cliente: {client.get('name','')}".strip()]
    if client.get("description"):
        parts.append(f"Descrição: {client['description']}".strip())
    return "\n".join([p for p in parts if p])

def get_templates(client: dict) -> Dict[str, str]:
    try:
        data = json.loads(client.get("templates_json") or "{}")
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def system_prompt(client: dict) -> str:
    sp = (client.get("system_prompt") or "").strip()
    if sp:
        return sp
    return ("Você é um estrategista e copywriter sênior para Instagram. "
            "Responda em PT-BR, objetivo, comercial e aplicável. Evite promessas irreais.")

def build_prompt(client: dict, content_type: str, n: int, extra: str = "", transcript: str = "") -> str:
    templates = get_templates(client)
    tpl = (templates.get(content_type) or DEFAULT_TEMPLATES[content_type]).format(n=n)
    parts = ["CONTEXTO DO CLIENTE:\n" + client_context(client)]
    if transcript.strip():
        parts.append("TRANSCRIÇÃO:\n" + transcript.strip())
    if extra.strip():
        parts.append("EXTRA:\n" + extra.strip())
    parts.append("TAREFA:\n" + tpl)
    return "\n\n---\n\n".join(parts)
