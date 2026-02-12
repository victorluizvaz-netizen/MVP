import os
from typing import Dict, List
import streamlit as st
from groq import Groq
from .base import LLMProvider

class GroqProvider(LLMProvider):
    key_name = "groq"

    def __init__(self) -> None:
        api_key = None
        if hasattr(st, "secrets") and "GROQ_API_KEY" in st.secrets:
            api_key = st.secrets["GROQ_API_KEY"]
        if not api_key:
            api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY não configurada (Streamlit secrets ou variável de ambiente).")
        self.client = Groq(api_key=api_key)

    def available_models(self) -> List[str]:
        # mantemos estático para MVP
        return [
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
        ]

    def chat(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> str:
        resp = self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
