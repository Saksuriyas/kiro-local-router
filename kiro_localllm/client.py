"""LLM providers: Ollama native API, and OpenAI-compatible (OpenRouter / custom)."""
from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from .config import env, env_bool, env_int


class LLMError(RuntimeError):
    pass


@dataclass
class Profile:
    name: str
    kind: str  # "ollama" | "openai"
    base_url: str
    model: str
    api_key: str = ""
    external: bool = False
    num_ctx: int = 8192


def load_profile(name: str | None = None) -> Profile:
    name = (name or env("DEFAULT_PROFILE", "local")).lower()
    if name == "local":
        return Profile(
            name="local",
            kind="ollama",
            base_url=env("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
            model=env("OLLAMA_MODEL", "qwen3:4b"),
            num_ctx=env_int("OLLAMA_NUM_CTX", 8192),
        )
    if name == "openrouter":
        return Profile(
            name="openrouter",
            kind="openai",
            base_url="https://openrouter.ai/api/v1",
            model=env("OPENROUTER_MODEL"),
            api_key=env("OPENROUTER_API_KEY"),
            external=True,
        )
    if name == "custom":
        return Profile(
            name="custom",
            kind="openai",
            base_url=env("CUSTOM_BASE_URL").rstrip("/"),
            model=env("CUSTOM_MODEL"),
            api_key=env("CUSTOM_API_KEY"),
            external=not env_bool("CUSTOM_IS_INTERNAL"),
        )
    raise LLMError(f"unknown profile '{name}' (use: local | openrouter | custom)")


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"\A\s*```(?:markdown|md)?\s*\n(.*)\n```\s*\Z", re.DOTALL)


def clean(text: str) -> str:
    """Drop <think> blocks and an outer ```markdown fence if the model added one."""
    text = _THINK.sub("", text).strip()
    m = _FENCE.match(text)
    return (m.group(1) if m else text).strip()


def chat(system: str, user: str, profile: str | None = None, model: str | None = None,
         temperature: float = 0.2) -> str:
    p = load_profile(profile)
    if p.external and not env_bool("ALLOW_EXTERNAL_PROVIDERS"):
        raise LLMError(
            f"profile '{p.name}' sends data outside your machine/network and is disabled. "
            "Set ALLOW_EXTERNAL_PROVIDERS=true in .env if your policy allows it."
        )
    chosen = model or p.model
    if not chosen:
        raise LLMError(f"no model configured for profile '{p.name}' (see .env)")
    timeout = env_int("LLM_TIMEOUT", 900)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        if p.kind == "ollama":
            body: dict = {
                "model": chosen,
                "messages": messages,
                "stream": False,
                "options": {"num_ctx": p.num_ctx, "temperature": temperature},
            }
            if env("OLLAMA_THINK").lower() == "false":
                body["think"] = False
            r = httpx.post(f"{p.base_url}/api/chat", json=body, timeout=timeout)
            if r.status_code == 404:
                raise LLMError(f"model '{chosen}' not found. Run: ollama pull {chosen}")
            r.raise_for_status()
            return clean(r.json()["message"]["content"])
        if not p.base_url:
            raise LLMError(f"profile '{p.name}' has no base URL (see .env)")
        r = httpx.post(
            f"{p.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {p.api_key}"},
            json={"model": chosen, "messages": messages, "temperature": temperature},
            timeout=timeout,
        )
        r.raise_for_status()
        return clean(r.json()["choices"][0]["message"]["content"])
    except httpx.ConnectError:
        hint = " Is Ollama running? Try: ollama serve" if p.kind == "ollama" else ""
        raise LLMError(f"cannot connect to {p.base_url}.{hint}")
    except httpx.TimeoutException:
        raise LLMError(f"timed out after {timeout}s waiting for {p.name}/{chosen}")
    except httpx.HTTPStatusError as e:
        raise LLMError(f"{p.name} returned HTTP {e.response.status_code}: {e.response.text[:300]}")


def ping(profile: str | None = None) -> str:
    """Return a short status string; raises LLMError when the provider is unreachable."""
    p = load_profile(profile)
    try:
        if p.kind == "ollama":
            r = httpx.get(f"{p.base_url}/api/tags", timeout=10)
            r.raise_for_status()
            names = [m["name"] for m in r.json().get("models", [])]
            if p.model not in names and f"{p.model}:latest" not in names:
                raise LLMError(f"Ollama is up but model '{p.model}' is not pulled. Run: ollama pull {p.model}")
            return f"ollama @ {p.base_url}, model {p.model} ready ({len(names)} models installed)"
        return f"{p.name} @ {p.base_url}, model {p.model or '(unset)'} (not probed)"
    except httpx.HTTPError as e:
        raise LLMError(f"cannot reach {p.base_url}: {e}")
