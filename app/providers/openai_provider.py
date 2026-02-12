from typing import Dict, List
from .base import LLMProvider

class OpenAIProvider(LLMProvider):
    key_name = "openai"

    def __init__(self) -> None:
        raise RuntimeError("Provider OpenAI ainda não foi configurado neste MVP. (Eu deixei o arquivo pronto.)")

    def available_models(self) -> List[str]:
        return []

    def chat(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> str:
        raise NotImplementedError
