from typing import Dict, List, Optional
from .text_utils import normalize_text, chunk_text
from ..providers.base import LLMProvider

DEFAULT_SYSTEM = (
    "Você é um estrategista de marketing e copywriter focado em Instagram. "
    "Seja direto, não invente dados, não prometa resultados garantidos. "
    "Escreva em português do Brasil."
)

def build_client_context(client: Dict) -> str:
    profile = client.get("profile") or {}
    parts = []
    parts.append(f"Cliente: {client.get('name','')}")
    if client.get("description"):
        parts.append(f"Descrição: {client['description']}")
    if profile:
        # campos comuns
        for k in ["nicho", "publico", "tom_de_voz", "oferta", "diferenciais", "provas", "restricoes", "cta"]:
            v = profile.get(k)
            if v:
                parts.append(f"{k.replace('_',' ').title()}: {v}")
    return "\n".join(parts).strip()

def run_task(
    provider: LLMProvider,
    model: str,
    client: Dict,
    instruction: str,
    input_text: str = "",
    temperature: float = 0.3,
    max_tokens: int = 1200,
    system_prompt: str = DEFAULT_SYSTEM,
    chunking: bool = True,
) -> str:
    ctx = build_client_context(client)
    input_text = normalize_text(input_text or "")
    user_payload = f"Contexto do cliente:\n{ctx}\n\nTarefa:\n{instruction}".strip()
    if input_text:
        user_payload += f"\n\nMaterial de apoio (ex.: transcrição):\n{input_text}"

    if not chunking or len(input_text) <= 6000:
        return provider.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_payload},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # chunking do material de apoio
    chunks = chunk_text(input_text, max_chars=6000)
    partials=[]
    for i,ch in enumerate(chunks, start=1):
        partials.append(
            provider.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"{user_payload}\n\n[Bloco {i}/{len(chunks)}]\n{ch}"},
                ],
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        )
    joined="\n\n".join([f"[BLOCO {i+1}]\n{p}" for i,p in enumerate(partials)])
    return provider.chat(
        messages=[
            {"role":"system","content":system_prompt},
            {"role":"user","content":"Consolide numa resposta final, sem repetir blocos:\n\n"+joined},
        ],
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )



DEFAULT_TEMPLATES = {
    "Ideias": "Gere {n} ideias de vídeos para Instagram Reels. Para cada ideia, entregue: (1) gancho, (2) promessa, (3) roteiro em 5-7 bullets, (4) CTA final. Foque em dores e objeções do público. Evite jargões desnecessários.",
    "Copy Reels": "Crie {n} variações de copy para um Reels no formato: Gancho (1-2 linhas) + Desenvolvimento (3-6 linhas) + CTA (1 linha). Use linguagem direta e alinhada ao tom de voz do cliente.",
    "Carrossel": "Crie {n} roteiros de carrossel. Para cada um: Título (slide 1), estrutura de 6-9 slides com textos curtos por slide, e CTA no último slide. Seja educativo e prático.",
    "Campanha": "Crie {n} ideias de campanha (Meta Ads) para levar ao WhatsApp. Para cada uma: ângulo, promessa, criativo sugerido, copy principal, headline, descrição, e CTA.",
    "Stories": "Crie {n} sequências de stories (4-7 telas). Para cada sequência: objetivo, texto por tela, interação (enquete/caixa/pergunta) e CTA.",
    "Roteiro": "Crie {n} roteiros completos de vídeo (30-60s) com: cena/ação, fala, on-screen text, cortes sugeridos e CTA final.",
}

def get_system_prompt(client: Dict, fallback: str = DEFAULT_SYSTEM) -> str:
    profile = client.get("profile") or {}
    custom = (profile.get("system_prompt") or "").strip()
    if custom:
        return custom
    return fallback

def build_instruction(client: Dict, content_type: str, n: int = 1, extra: str = "") -> str:
    profile = client.get("profile") or {}
    prefs = profile.get("format_prefs") or {}
    template = prefs.get(content_type) or DEFAULT_TEMPLATES.get(content_type) or "Crie conteúdo para Instagram."
    instr = template.format(n=n)
    if extra:
        instr += "\n\nContexto extra do usuário: " + extra.strip()
    return instr
