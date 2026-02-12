import os
import streamlit as st

class GroqProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    @classmethod
    def from_env_or_secrets(cls) -> "GroqProvider":
        key = os.environ.get("GROQ_API_KEY")
        if not key and hasattr(st, "secrets"):
            try:
                key = st.secrets.get("GROQ_API_KEY")
            except Exception:
                key = None
        if not key:
            raise RuntimeError("GROQ_API_KEY não configurada (env ou Streamlit Secrets).")
        return cls(api_key=key)

    def chat(self, model: str, system: str, user: str, temperature: float = 0.7, max_tokens: int = 1400) -> str:
        from groq import Groq
        client = Groq(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role":"system","content":system},{"role":"user","content":user}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
