"""Thin Groq chat-completions client (OpenAI-compatible endpoint).

The API key is read from the GROQ_API_KEY environment variable only -- it is
never written to source, logs, or responses.

Default model: qwen/qwen3.6-27b. If that model is decommissioned or not enabled
on the account, the client transparently falls back through
config.GROQ_FALLBACK_MODELS and remembers whichever one works.
"""
import json
import re
import threading
import time
from typing import Optional

import requests

from . import config


class GroqError(RuntimeError):
    pass


_lock = threading.Lock()
_active: Optional[str] = None          # model confirmed working this process
_dead: set = set()                     # models the API rejected

# Reasoning models emit a thinking preamble; strip it if any leaks through.
_THINK = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.S | re.I)
_OPEN_THINK = re.compile(r"^\s*<(think|thinking|reasoning)>.*?(?=\n\n|\Z)", re.S | re.I)


def available() -> bool:
    return bool(config.GROQ_API_KEY)


def active_model() -> str:
    return _active or config.GROQ_MODEL


def _candidates() -> list:
    """Preferred model first, then configured fallbacks, minus known-dead ones."""
    ordered = [active_model()] + [m for m in config.GROQ_FALLBACK_MODELS
                                  if m != active_model()]
    live = [m for m in ordered if m not in _dead]
    return live or ordered[:1]


def _is_reasoning(model: str) -> bool:
    m = model.lower()
    return ("qwen3" in m or "gpt-oss" in m or "minimax" in m
            or "qwq" in m or "deepseek-r1" in m)


def _strip_reasoning(text: str) -> str:
    text = _THINK.sub("", text)
    text = _OPEN_THINK.sub("", text)
    return text.strip()


def _payload(model: str, messages: list, temperature: float, max_tokens: int,
             json_mode: bool) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if _is_reasoning(model):
        effort = config.GROQ_REASONING_EFFORT
        if effort and effort != "off":
            body["reasoning_effort"] = effort  # "none" keeps prose fast and clean
        body["reasoning_format"] = "hidden"
    return body


def _model_unavailable(status: int, text: str) -> bool:
    lowered = (text or "").lower()
    return status in (400, 404) and any(
        s in lowered for s in ("model_not_found", "does not exist", "decommissioned",
                               "not supported", "no longer supported", "invalid model"))


def _unsupported_param(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for param in ("reasoning_effort", "reasoning_format", "response_format"):
        if param in lowered and ("unsupported" in lowered or "not supported" in lowered
                                 or "invalid" in lowered or "unrecognized" in lowered):
            return param
    return None


def chat(messages: list, *, temperature: float = 0.75, max_tokens: int = 4096,
         json_mode: bool = False, retries: int = 3) -> str:
    global _active
    if not available():
        raise GroqError("GROQ_API_KEY is not configured")

    last_err: Optional[Exception] = None
    for model in _candidates():
        body = _payload(model, messages, temperature, max_tokens, json_mode)
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
                    detail = resp.text[:400]
                    if _model_unavailable(resp.status_code, detail):
                        with _lock:
                            _dead.add(model)
                        print(f"[lifescroll] model '{model}' unavailable, trying next")
                        last_err = GroqError(f"model '{model}' unavailable: {detail}")
                        break  # next candidate model
                    stray = _unsupported_param(detail)
                    if stray and stray in body:
                        body.pop(stray, None)  # retry without the offending field
                        print(f"[lifescroll] dropping unsupported param '{stray}'")
                        continue
                    if resp.status_code >= 500:
                        time.sleep(1.5 * (attempt + 1))
                        last_err = GroqError(f"Groq API {resp.status_code}")
                        continue
                    raise GroqError(f"Groq API {resp.status_code}: {detail}")

                if model != _active:
                    with _lock:
                        _active = model
                        config.ACTIVE_MODEL = model
                content = resp.json()["choices"][0]["message"]["content"] or ""
                return _strip_reasoning(content)
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
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.S)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
    raise GroqError("Model did not return valid JSON")
