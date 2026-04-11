"""
Cloud API backend — Gemini and Groq.

Used in demo/hosted mode when Ollama is not available.
Both providers are wrapped behind a common streaming interface.

Gemini: uses REST streaming endpoint
Groq:   uses OpenAI-compatible streaming endpoint
"""

from __future__ import annotations

import json
import logging
from typing import Generator

import requests

logger = logging.getLogger(__name__)


class CloudAPIBackend:
    """
    Unified cloud LLM backend supporting Gemini and Groq.
    """

    def __init__(self, config: dict):
        api_cfg = config.get("llm", {}).get("api", {})
        self.provider = api_cfg.get("provider", "gemini").lower()
        self.api_key = api_cfg.get("api_key", "")
        self.gemini_model = api_cfg.get("gemini_model", "gemma-2-9b-it")
        self.groq_model = api_cfg.get("groq_model", "llama-3.1-8b-instant")
        self._request_timeout = int(config.get("llm", {}).get("request_timeout", 120))

        ollama_cfg = config.get("llm", {}).get("ollama", {})
        self.temp_analytical = float(ollama_cfg.get("temperature_analytical", 0.3))
        self.temp_conversational = float(ollama_cfg.get("temperature_conversational", 0.7))

        if not self.api_key:
            logger.warning(
                "Cloud API key not set. "
                "Set GEMINI_API_KEY or GROQ_API_KEY environment variable."
            )

    def health_check(self) -> bool:
        """Return True if we have an API key configured."""
        return bool(self.api_key)

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = None,
    ) -> Generator[str, None, None]:
        temp = temperature if temperature is not None else self.temp_analytical
        if self.provider == "groq":
            yield from self._groq_stream(messages, temp)
        else:
            yield from self._gemini_stream(messages, temp)

    def chat_complete(
        self,
        messages: list[dict],
        temperature: float = None,
    ) -> str:
        return "".join(self.chat_stream(messages, temperature=temperature))

    # -----------------------------------------------------------------------
    # Gemini
    # -----------------------------------------------------------------------

    def _gemini_stream(
        self, messages: list[dict], temperature: float
    ) -> Generator[str, None, None]:
        # Convert messages to Gemini format
        system_text = ""
        contents = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            if role == "system":
                system_text = content
                continue
            gemini_role = "user" if role == "user" else "model"
            contents.append({
                "role": gemini_role,
                "parts": [{"text": content}],
            })

        # Prepend system text to first user message
        if system_text and contents:
            for item in contents:
                if item["role"] == "user":
                    item["parts"][0]["text"] = (
                        f"{system_text}\n\n{item['parts'][0]['text']}"
                    )
                    break

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": 8192,
            },
        }

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:streamGenerateContent"
            f"?key={self.api_key}&alt=sse"
        )

        try:
            with requests.post(
                url,
                json=payload,
                stream=True,
                timeout=self._request_timeout,
                headers={"Content-Type": "application/json"},
            ) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Gemini API error {resp.status_code}: {resp.text[:400]}"
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    raw = line.decode("utf-8") if isinstance(line, bytes) else line
                    if raw.startswith("data: "):
                        raw = raw[6:]
                    if raw in ("[DONE]", ""):
                        continue
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        text = (
                            data["candidates"][0]["content"]["parts"][0]["text"]
                        )
                        if text:
                            yield text
                    except (KeyError, IndexError):
                        pass

        except requests.exceptions.ConnectionError:
            raise ConnectionError("Cannot reach Gemini API. Check your internet connection.")
        except requests.exceptions.Timeout:
            raise TimeoutError("Gemini API did not respond in time.")

    # -----------------------------------------------------------------------
    # Groq (OpenAI-compatible)
    # -----------------------------------------------------------------------

    def _groq_stream(
        self, messages: list[dict], temperature: float
    ) -> Generator[str, None, None]:
        payload = {
            "model": self.groq_model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
            "max_tokens": 8192,
        }

        try:
            with requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload,
                stream=True,
                timeout=self._request_timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Groq API error {resp.status_code}: {resp.text[:400]}"
                    )
                for line in resp.iter_lines():
                    if not line:
                        continue
                    raw = line.decode("utf-8") if isinstance(line, bytes) else line
                    if raw.startswith("data: "):
                        raw = raw[6:]
                    if raw == "[DONE]":
                        break
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    try:
                        delta = data["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (KeyError, IndexError):
                        pass

        except requests.exceptions.ConnectionError:
            raise ConnectionError("Cannot reach Groq API. Check your internet connection.")
        except requests.exceptions.Timeout:
            raise TimeoutError("Groq API did not respond in time.")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_backend(config: dict):
    """
    Create the appropriate backend based on config['llm']['backend'].
    Returns an object with .chat_stream(), .chat_complete(), .health_check() methods.
    """
    from engine.backends.ollama import OllamaBackend

    backend_type = config.get("llm", {}).get("backend", "ollama").lower()

    if backend_type == "api":
        return CloudAPIBackend(config)
    else:
        return OllamaBackend(config)
