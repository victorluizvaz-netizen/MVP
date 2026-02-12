from abc import ABC, abstractmethod
from typing import Dict, List, Optional

class LLMProvider(ABC):
    key_name: str  # for display

    @abstractmethod
    def available_models(self) -> List[str]:
        raise NotImplementedError

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]], model: str, temperature: float, max_tokens: int) -> str:
        raise NotImplementedError
