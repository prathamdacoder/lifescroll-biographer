"""Thin Groq chat-completions client (OpenAI-compatible endpoint).

The API key is read from the GROQ_API_KEY environment variable only -- it is
never written to source, logs, or responses.
"""
import json
import re
import time
from typing import Optional

import requests

from . import config


class GroqError(RuntimeError):
    pass


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def chat(messages: list, *, temperature: float = 0.75, max_tokens: int = 4096,
         json_mode: bool = False, retries: int = 3) -> str:
    if not available():
        raise GroqError("GROQ_API_KEY is not configured")

    body = {
        "model": config.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}

    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                f"{config.GROQ_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}",
                         "Content-Type": "application/json"},
                json=body,
                timeout=180,
            )
            if resp.status_code == 429:
                time.sleep(2 ** attempt * 2)
                last_err = GroqError("rate limited")
                continue
            if resp.status_code >= 400:
                detail = resp.text[:300]
                raise GroqError(f"Groq API {resp.status_code}: {detail}")
            return resp.json()["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise GroqError(f"Groq request failed: {last_err}")


def chat_json(messages: list, *, temperature: float = 0.6, max_tokens: int = 4096) -> dict:
    """Chat call that must return a JSON object; tolerant of stray prose."""
    raw = chat(messages, temperature=temperature, max_tokens=max_tokens, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    raise GroqError("Model did not return valid JSON")
