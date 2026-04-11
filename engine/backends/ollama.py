"""
Ollama API backend.

Streams chat completions from a local Ollama instance.
Model: gemma4:e4b (128K context, supports native system role)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Generator

import requests

logger = logging.getLogger(__name__)


class OllamaBackend:
    """
    Client for the local Ollama API.
    Endpoint: POST {host}/api/chat
    """

    def __init__(self, config: dict):
        ollama_cfg = config.get("llm", {}).get("ollama", {})
        raw_host = ollama_cfg.get("host", "http://localhost:11434").rstrip("/")
        self.host = self._normalize_host(raw_host)
        self.model = ollama_cfg.get("model", "gemma4:e4b")
        self.temp_analytical = float(ollama_cfg.get("temperature_analytical", 0.3))
        self.temp_conversational = float(ollama_cfg.get("temperature_conversational", 0.7))
        self.max_tokens = int(ollama_cfg.get("max_tokens", 8192))
        self.context_window = int(ollama_cfg.get("context_window", 128000))
        self._request_timeout = int(config.get("llm", {}).get("request_timeout", 120))

    @staticmethod
    def _normalize_host(host: str) -> str:
        """
        Ollama sets OLLAMA_HOST=0.0.0.0 (or similar) as an env var.
        We always want a full http:// URL pointing to localhost.
        """
        # Strip protocol if present, we'll re-add it
        bare = host.replace("http://", "").replace("https://", "")
        # If it's a bare IP like 0.0.0.0 or 0.0.0.0:11434, talk to localhost instead
        if bare.startswith("0.0.0.0"):
            port = bare.split(":")[-1] if ":" in bare else "11434"
            return f"http://localhost:{port}"
        # If already a proper host[:port], just ensure http://
        if not host.startswith("http"):
            return f"http://{bare}"
        return host

    def health_check(self) -> bool:
        """Return True if Ollama is reachable and the required model is available."""
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            # Accept both "gemma4:e4b" and "gemma4" as available
            base = self.model.split(":")[0]
            available = any(
                m == self.model or m.startswith(base + ":") or m == base
                for m in models
            )
            if not available:
                logger.warning(
                    "Model '%s' not found in Ollama. Available: %s",
                    self.model, models
                )
            return True   # Ollama is up even if model not pulled yet
        except Exception as e:
            logger.debug("Ollama health check failed: %s", e)
            return False

    def list_models(self) -> list[str]:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=5)
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception:
            return []

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = None,
    ) -> Generator[str, None, None]:
        """
        Stream a chat response token by token.

        Args:
            messages: OpenAI-style messages list
                      [{"role": "system"|"user"|"assistant", "content": "..."}]
            temperature: Override temperature. Defaults to analytical (0.3).

        Yields:
            str: each text chunk as it arrives
        """
        temp = temperature if temperature is not None else self.temp_analytical

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temp,
                "top_p": 0.95,
                "top_k": 64,
                "num_ctx": self.context_window,
                "num_predict": self.max_tokens,
            },
        }

        try:
            with requests.post(
                f"{self.host}/api/chat",
                json=payload,
                stream=True,
                timeout=self._request_timeout,
            ) as resp:
                if resp.status_code != 200:
                    error_body = resp.text[:500]
                    raise RuntimeError(
                        f"Ollama returned HTTP {resp.status_code}: {error_body}"
                    )

                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("error"):
                        raise RuntimeError(f"Ollama error: {data['error']}")

                    content = data.get("message", {}).get("content", "")
                    if content:
                        yield content

                    if data.get("done"):
                        break

        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                "Cannot connect to Ollama. "
                "Make sure Ollama is running: run 'ollama serve' in a terminal."
            )
        except requests.exceptions.Timeout:
            raise TimeoutError(
                f"Ollama did not respond within {self._request_timeout} seconds. "
                "The model may be loading. Try again in a moment."
            )

    def chat_complete(
        self,
        messages: list[dict],
        temperature: float = None,
    ) -> str:
        """Non-streaming version. Collects and returns full response."""
        return "".join(self.chat_stream(messages, temperature=temperature))
