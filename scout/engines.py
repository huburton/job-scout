"""Available models and grammar-constrained JSON calls (llama.cpp, OpenAI-compatible API).

- Fact extraction: always the main model (reachable all the time, never touches the second machine).
- "Is this job for the candidate?" judgement: the optional bigger model on a second machine when it can run
  without disturbing its owner, otherwise the main model; the bigger model then re-judges what the main one
  rated (after each run, and every 15 minutes while it is available).
  "Possible" = machine on, user idle (status endpoint) and the model fits entirely in VRAM: AI mode on, or enough
  free VRAM to load it. Otherwise the router would offload layers to the CPU (slow, hot).
Without SCOUT_PC_STATUS_URL the second machine is simply never used.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from . import config

log = logging.getLogger("scout.engines")


@dataclass
class Engine:
    label: str
    url: str
    key: str
    model: str
    extra: dict = field(default_factory=lambda: {"chat_template_kwargs": {"enable_thinking": False}})
    was_loaded: bool = True  # big model already loaded before us (otherwise it is unloaded after the batch)


def _key(value: str, path: str) -> str:
    if value:
        return value
    try:
        return Path(path).read_text().strip() if path else ""
    except OSError:
        return ""


def server() -> Engine:
    return Engine("server", config.LLM_URL, _key(config.LLM_KEY, config.LLM_KEY_FILE), config.LLM_MODEL)


def _pc_key() -> str:
    return _key(config.PC_KEY, config.PC_KEY_FILE)


def _pc_status() -> dict | None:
    if not config.PC_STATUS_URL:
        return None
    try:
        r = httpx.get(config.PC_STATUS_URL, headers={"Authorization": f"Bearer {_pc_key()}"}, timeout=3)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError):
        return None


def judge() -> Engine:
    st = _pc_status()
    if not st or st.get("models") is None or not st.get("user_idle"):
        return server()  # machine off, router down or user at the keyboard: leave the GPU alone
    # No "already loaded" shortcut: a big model loaded next to an animated wallpaper runs partly on the CPU
    loaded = any(m["id"] == config.PC_MODEL and m.get("status") == "loaded" for m in st["models"])
    gpu = st.get("gpu") or {}
    free = gpu.get("vram_total_mib", 0) - gpu.get("vram_used_mib", 0)
    if st.get("ai_mode") or (not loaded and free >= config.PC_MODEL_MIB):
        return Engine("pc-big", config.PC_LLM_URL, _pc_key(), config.PC_MODEL, was_loaded=loaded)
    return server()


def still_free(engine: Engine) -> bool:
    """Is the user still away? (checked during a batch: if they come back, the machine is given back)"""
    st = _pc_status()
    return engine.label != "pc-big" or bool(st and st.get("user_idle"))


def release(engine: Engine):
    """Unload the big model if this job loaded it (VRAM is free again when the user comes back)."""
    if engine.label != "pc-big" or engine.was_loaded:
        return
    try:
        httpx.post(config.PC_STATUS_URL.rsplit("/", 1)[0] + "/llm/unload", json={"model": engine.model},
                   headers={"Authorization": f"Bearer {engine.key}"}, timeout=30)
    except httpx.HTTPError:
        log.warning("could not unload the big model (it unloads itself after a while)")


def chat_json(engine: Engine, content: str, schema: dict, max_tokens: int = 900, timeout: float = 600) -> dict:
    if config.DEMO:
        from . import demo
        return demo.fake_chat_json(content, schema)
    last = None
    for penalty in (0.0, 1.0):  # 2nd try with a repetition penalty if the output is truncated
        r = httpx.post(f"{engine.url}/chat/completions", headers={"Authorization": f"Bearer {engine.key}"},
                       timeout=httpx.Timeout(timeout, connect=5), json={
                           "model": engine.model, "temperature": 0, "max_tokens": max_tokens,
                           "presence_penalty": penalty, **engine.extra,
                           "messages": [{"role": "user", "content": content}],
                           "response_format": {"type": "json_schema",
                                               "json_schema": {"name": "reponse", "schema": schema}},
                       })
        r.raise_for_status()
        try:
            return json.loads(r.json()["choices"][0]["message"]["content"])
        except json.JSONDecodeError as e:
            last = e
    raise last
