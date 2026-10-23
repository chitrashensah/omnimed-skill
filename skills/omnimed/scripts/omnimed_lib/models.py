# Model registry and provider calls for the OmniMed skill.
#
# Mirrors the backend's model keys (routes/chat.py) on purpose: a key is what
# gets written into `validations.model`, so an answer gathered here and one
# gathered on the website must carry the same key for the same model, or the
# two datasets cannot be pooled.
#
# Plain HTTP via httpx rather than each provider's SDK. The skill should
# install with one small dependency; the six SDKs the backend uses would turn
# a skill install into a dependency-resolution exercise.
#
# Every call returns the same shape:
#   {model, label, status: "ok"|"error", text?, error?, served_model?,
#    usage: {input, output}, seconds}

import asyncio
import os
import re
import time

import httpx

from . import env

TIMEOUT = 300.0              # a research answer can legitimately take minutes
ANTHROPIC_MAX_TOKENS = 16000  # thinking shares this budget with the answer
# Same as the website: thinking on (adaptive) and effort "high" on every
# Claude model; Opus 5.5 and Haiku 5.5 would otherwise default to "medium".
ANTHROPIC_EFFORT = "high"
GEMINI_MAX_TOKENS = 8192
OPENAI_LIKE_MAX_TOKENS = 16384
RETRY_WAIT = 15              # one retry on a provider's "busy" response
# Reasoning models (Qwen 3.8, Command A+) think before answering, and the
# thinking shares the output budget. Uncapped, both spent all 16,384 tokens
# thinking on a DOX-cardiotoxicity question and returned nothing (2026-10-21).
# Capped at 6,000, both answered: Qwen in 87s, Cohere in 43s.
REASONING_BUDGET = 6000

OPENROUTER_URL = "https://openrouter.ai/api/v1"

# The same 25 models the website offers (omnimed-frontend/src/pages/Chat.jsx
# MODELS), with the same keys, labels, groups and colours, so a comparison here
# looks and records like one on the site. Keys are permanent: they are written
# into validations.model. Never rename one or point it at a different model.
#
# tier: "free"  — a free API tier exists for this provider
#       "cheap" — paid, but fractions of a cent per answer
#       "paid"  — billed per token at premium rates
def _m(label, provider, model_id, tier, group, color, bg, **extra):
    return {"label": label, "provider": provider, "id": model_id, "tier": tier,
            "group": group, "color": color, "bg": bg, **extra}


_OAI = {"token_param": "max_completion_tokens"}

MODELS = {
    # Anthropic
    "opus55":   _m("Claude Opus 5.5",   "anthropic", "claude-opus-5-5",   "paid", "Anthropic", "#6d28d9", "#ede9fe"),
    "sonnet55": _m("Claude Sonnet 5.5", "anthropic", "claude-sonnet-5-5", "paid", "Anthropic", "#7c3aed", "#f5f3ff"),
    "haiku55":  _m("Claude Haiku 5.5",  "anthropic", "claude-haiku-5-5",  "paid", "Anthropic", "#9333ea", "#faf5ff"),
    "fable51":  _m("Claude Fable 5.1",  "anthropic", "claude-fable-5-1",  "paid", "Anthropic", "#7e22ce", "#f3e8ff"),
    "opus5":    _m("Claude Opus 5",     "anthropic", "claude-opus-5",     "paid", "Anthropic", "#6d28d9", "#ede9fe"),
    "sonnet5":  _m("Claude Sonnet 5",   "anthropic", "claude-sonnet-5",   "paid", "Anthropic", "#7c3aed", "#f5f3ff"),
    # OpenAI — every id here takes max_completion_tokens, not max_tokens
    "gpt61sol":  _m("GPT-6.1 Sol",  "openai", "gpt-6.1-sol",  "paid",  "OpenAI", "#15803d", "#dcfce7", **_OAI),
    "gpt6astra": _m("GPT-6 Astra",  "openai", "gpt-6-astra",  "paid",  "OpenAI", "#15803d", "#dcfce7", **_OAI),
    "gpt6luna":  _m("GPT-6 Luna",   "openai", "gpt-6-luna",   "paid",  "OpenAI", "#16a34a", "#dcfce7", **_OAI),
    "gpt55":     _m("GPT-5.5",      "openai", "gpt-5.5",      "paid",  "OpenAI", "#166534", "#dcfce7", **_OAI),
    "gpt54mini": _m("GPT-5.4 mini", "openai", "gpt-5.4-mini", "cheap", "OpenAI", "#047857", "#d1fae5", **_OAI),
    # DeepSeek
    "deepseek_pro": _m("DeepSeek V4 Pro", "deepseek", "deepseek-v4-pro", "cheap", "DeepSeek", "#0369a1", "#e0f2fe"),
    # Google — Flash tiers; Pro and Gemini 4 Argon need a paid plan (429 on a free key)
    "gemini38": _m("Gemini 3.8 Flash", "google", "gemini-3.8-flash", "free", "Google", "#b45309", "#fef3c7"),
    "gemini37": _m("Gemini 3.7 Flash", "google", "gemini-3.7-flash", "free", "Google", "#b45309", "#fef3c7"),
    "gemini36": _m("Gemini 3.6 Flash", "google", "gemini-3.6-flash", "free", "Google", "#b45309", "#fef3c7"),
    "gemini":   _m("Gemini 2.5 Flash", "google", "gemini-2.5-flash", "free", "Google", "#ca8a04", "#fef3c7"),
    # Qwen — via OpenRouter (paid credit) or Groq (free tier, rate-limited)
    "qwen38flash":   _m("Qwen 3.8 Flash",      "openrouter", "qwen/qwen3.8-flash",    "cheap", "Qwen", "#be185d", "#fce7f3"),
    "qwen38max0902": _m("Qwen 3.8 Max",        "openrouter", "qwen/qwen3.8-max-0902", "cheap", "Qwen", "#be185d", "#fce7f3"),
    "qwen37plus":    _m("Qwen 3.7 Plus",       "openrouter", "qwen/qwen3.7-plus",     "cheap", "Qwen", "#db2777", "#fce7f3"),
    "qwen36flash":   _m("Qwen 3.6 Flash",      "openrouter", "qwen/qwen3.6-flash",    "cheap", "Qwen", "#9d174d", "#fce7f3"),
    "groq_qwen38":   _m("Qwen 3.8 27B (Groq)", "groq",       "qwen/qwen3.8-27b",      "free",  "Qwen", "#a21caf", "#fae8ff"),
    # Other providers
    "groq":   _m("Groq GPT-OSS 120B", "groq",   "openai/gpt-oss-120b",    "free", "Other", "#c2410c", "#ffedd5"),
    "cohere": _m("Cohere Command A+", "cohere", "command-a-plus-05-2026", "free", "Other", "#0f766e", "#ccfbf1"),
}

PROVIDERS = ("anthropic", "openai", "google", "groq", "deepseek", "openrouter", "cohere")

# The site's five default boxes and its five-box limit (Chat.jsx DEFAULT_BOXES,
# MAX_BOXES). More than five answers side by side stops being readable.
SITE_DEFAULT = ("gemini38", "deepseek_pro", "groq", "qwen38flash", "cohere")
MAX_MODELS = 5

# The four checkbox questions of the model picker. A picker question holds at
# most four options, so each group lists its models in order of preference and
# the first four with a key configured are offered; the rest stay reachable by
# typing their name under "Other".
PICKER_GROUPS = (
    ("Google", "Google Gemini (free tier)",
     ("gemini38", "gemini37", "gemini36", "gemini")),
    ("Open models", "Open and low-cost models",
     ("deepseek_pro", "qwen38flash", "groq", "cohere", "groq_qwen38", "qwen38max0902", "qwen37plus", "qwen36flash")),
    ("OpenAI", "OpenAI GPT (paid)",
     ("gpt61sol", "gpt6astra", "gpt6luna", "gpt55", "gpt54mini")),
    ("Anthropic", "Anthropic Claude (paid)",
     ("opus55", "sonnet55", "haiku55", "fable51", "opus5", "sonnet5")),
)

# Judges, in order of preference. Measured on the backend (2026-10-01) by
# latency on a scoring-sized prompt: judging is an easy task every model here
# can do, so speed decides.
JUDGE_PREFERENCE = ("gemini36", "gemini", "gpt54mini", "groq", "groq_qwen38", "deepseek_pro", "qwen36flash")

# Plain-language names, so "compare Gemini, DeepSeek and GPT" resolves to the
# newest model of each family that the site offers by default.
ALIASES = {
    "gemini flash": "gemini38", "gemini 3.8": "gemini38", "gemini 3.7": "gemini37",
    "gemini 3.6": "gemini36", "gemini 2.5": "gemini",
    "gpt": "gpt55", "chatgpt": "gpt55", "openai": "gpt55", "gpt-5.5": "gpt55", "gpt 5.5": "gpt55",
    "gpt-6": "gpt6astra", "gpt 6": "gpt6astra", "gpt-6 astra": "gpt6astra", "gpt-6.1": "gpt61sol",
    "gpt-6.1 sol": "gpt61sol", "gpt-6 luna": "gpt6luna", "gpt luna": "gpt6luna",
    "gpt mini": "gpt54mini", "gpt-5.4 mini": "gpt54mini",
    "sonnet": "sonnet55", "claude sonnet": "sonnet55", "opus": "opus55",
    "claude opus": "opus55", "fable": "fable51", "claude fable": "fable51",
    "haiku": "haiku55", "claude haiku": "haiku55",
    "deepseek": "deepseek_pro", "deepseek v4": "deepseek_pro", "deepseek pro": "deepseek_pro",
    "qwen max": "qwen38max0902", "qwen flash": "qwen38flash", "qwen groq": "groq_qwen38",
    "qwen 27b": "groq_qwen38",
    "llama": "groq", "gpt-oss": "groq", "gpt oss": "groq",
    "command": "cohere", "command a": "cohere",
}


def _load_custom() -> None:
    """Merge models from ~/.config/omnimed/models.json, so a new model can be
    tried without editing this file:

        {"mistral_large": {"label": "Mistral Large", "provider": "openrouter",
                           "id": "mistralai/mistral-large", "tier": "cheap"}}

    Keys already in MODELS are never overridden: a key means one model forever.
    """
    import json
    path = env.CONFIG_DIR / "models.json"
    if not path.is_file():
        return
    try:
        custom = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    for key, spec in (custom or {}).items():
        if (not isinstance(spec, dict) or key in MODELS
                or spec.get("provider") not in PROVIDERS or not spec.get("id")):
            continue
        MODELS[key] = _m(spec.get("label") or key, spec["provider"], spec["id"],
                         spec.get("tier", "paid"), "Custom", "#475569", "#f1f5f9",
                         **({"token_param": spec["token_param"]} if spec.get("token_param") else {}))


_load_custom()


def resolve(name: str) -> str | None:
    n = (name or "").strip().lower()
    if n in MODELS:
        return n
    if n in ALIASES:
        return ALIASES[n]
    # Labels too: "Qwen 3.8 Max", "Claude Opus 4.8"
    for k, m in MODELS.items():
        if m["label"].lower() == n:
            return k
    return None


def available(key: str) -> bool:
    spec = MODELS.get(key)
    return bool(spec and env.has_key(spec["provider"]))


def default_set() -> list[str]:
    """OMNIMED_DEFAULT_MODELS if the user set one, else the site's defaults."""
    raw = os.getenv("OMNIMED_DEFAULT_MODELS", "")
    chosen = [resolve(x) for x in raw.split(",") if x.strip()]
    chosen = [k for k in dict.fromkeys(chosen) if k]
    return (chosen or list(SITE_DEFAULT))[:MAX_MODELS]


def catalog() -> list[dict]:
    defaults = default_set()
    return [{"key": k, "label": m["label"], "group": m["group"], "provider": m["provider"],
             "model_id": m["id"], "tier": m["tier"], "key_configured": available(k),
             "default": k in defaults}
            for k, m in MODELS.items()]


_TIER_NOTE = {"free": "free tier", "cheap": "low cost", "paid": "paid per answer"}


def picker() -> list[dict]:
    """Ready-made questions for a checkbox picker (e.g. AskUserQuestion):
    at most 4 questions of at most 4 options, only models with a key."""
    defaults = set(default_set())
    questions = []
    for header, title, keys in PICKER_GROUPS:
        shown = [k for k in keys if k in MODELS and available(k)][:4]
        if len(shown) < 2:      # a picker question needs at least two options
            continue
        hidden = [MODELS[k]["label"] for k in keys if k in MODELS and available(k) and k not in shown]
        q = f"{title}: which to include?"
        if hidden:
            q += f" (Also available by typing: {', '.join(hidden)})"
        questions.append({
            "header": header, "question": q, "multiSelect": True,
            "options": [{"label": MODELS[k]["label"] + (" (default)" if k in defaults else ""),
                         "description": f"{_TIER_NOTE[MODELS[k]['tier']]} · key: {k}"}
                        for k in shown],
        })
    return questions[:4]


def _usage(i=0, o=0) -> dict:
    return {"input": int(i or 0), "output": int(o or 0)}


def _error_for(status: int, body: str) -> str:
    low = (body or "").lower()
    if status in (401, 403):
        return "API_KEY_INVALID"
    # Same code as the website: an empty prepaid balance (Anthropic answers 400
    # "credit balance is too low", OpenRouter 402).
    if status == 402 or "insufficient" in low or "credit balance" in low or "credits" in low:
        return "INSUFFICIENT_CREDITS"
    if status == 429:
        return "RATE_LIMIT"
    if status in (500, 502, 503, 504, 529) or "overloaded" in low or "unavailable" in low:
        return "SERVICE_UNAVAILABLE"
    if status == 404 or "not found" in low and "model" in low:
        return "MODEL_UNAVAILABLE"
    return f"HTTP_{status}"


def _detail(body: str) -> str:
    """The provider's own explanation, shortened. URLs are removed: they can
    carry account or key identifiers, and the message is shown to the user."""
    try:
        import json as _json
        data = _json.loads(body)
        err = data.get("error") if isinstance(data, dict) else None
        msg = (err.get("message") if isinstance(err, dict) else err) or data.get("message") or ""
    except (ValueError, AttributeError):
        msg = body or ""
    msg = re.sub(r"https?://\S+", "[link]", str(msg))
    return re.sub(r"\s+", " ", msg).strip()[:240]


def _failure(r) -> dict:
    return {"status": "error", "error": _error_for(r.status_code, r.text), "detail": _detail(r.text)}


async def _post(client, url, headers, payload, retry=True):
    try:
        r = await client.post(url, headers=headers, json=payload)
    except (httpx.ReadError, httpx.RemoteProtocolError, httpx.ConnectError):
        # Long answers hold a connection open for minutes, and providers drop
        # some mid-reply (seen with OpenRouter at ~90s). One fresh attempt.
        if not retry:
            raise
        await asyncio.sleep(2)
        return await _post(client, url, headers, payload, retry=False)
    if r.status_code in (429, 503, 529) and retry:
        await asyncio.sleep(RETRY_WAIT)
        r = await client.post(url, headers=headers, json=payload)
    return r


def _turns(history, message) -> list[dict]:
    """Earlier exchanges (this model's own) followed by the new message."""
    return [{"role": h["role"], "content": h["content"]} for h in (history or [])
            if h.get("role") in ("user", "assistant") and h.get("content")] + \
           [{"role": "user", "content": message}]


async def _anthropic(client, spec, key, system, message, max_tokens, history=None):
    messages = _turns(history, message)
    if len(messages) > 1:
        # Cache everything up to the last earlier turn, as the website does: a
        # follow-up then pays full price only for what is new.
        last = messages[-2]
        last["content"] = [{"type": "text", "text": last["content"],
                            "cache_control": {"type": "ephemeral"}}]
    payload = {"model": spec["id"], "max_tokens": max(max_tokens, ANTHROPIC_MAX_TOKENS),
               "messages": messages,
               "thinking": {"type": "adaptive"}, "output_config": {"effort": ANTHROPIC_EFFORT}}
    if system:
        payload["system"] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    r = await _post(client, "https://api.anthropic.com/v1/messages",
                    {"x-api-key": key, "anthropic-version": "2023-06-01"}, payload)
    if r.status_code != 200:
        return _failure(r)
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    u = data.get("usage") or {}
    out = {"text": text, "served_model": data.get("model"),
           "usage": _usage(u.get("input_tokens"), u.get("output_tokens"))}
    if data.get("stop_reason") == "refusal":
        return {**out, "status": "error", "error": "REFUSED"}
    if not text.strip():
        err = "TRUNCATED_BEFORE_ANSWER" if data.get("stop_reason") == "max_tokens" else "EMPTY_RESPONSE"
        return {**out, "status": "error", "error": err}
    return {**out, "status": "ok"}


async def _gemini(client, spec, key, system, message, max_tokens, history=None):
    payload = {"contents": [{"role": "model" if t["role"] == "assistant" else "user",
                             "parts": [{"text": t["content"]}]} for t in _turns(history, message)],
               "generationConfig": {"maxOutputTokens": max(max_tokens, GEMINI_MAX_TOKENS)}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{spec['id']}:generateContent"
    r = await _post(client, url, {"x-goog-api-key": key}, payload)
    if r.status_code != 200:
        return _failure(r)
    data = r.json()
    cands = data.get("candidates") or []
    parts = ((cands[0].get("content") or {}).get("parts") or []) if cands else []
    # Thought parts are flagged `thought: true`; only the visible answer counts.
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = data.get("usageMetadata") or {}
    out = {"text": text, "served_model": data.get("modelVersion") or spec["id"],
           "usage": _usage(u.get("promptTokenCount"), u.get("candidatesTokenCount"))}
    if not text.strip():
        reason = cands[0].get("finishReason") if cands else None
        err = "TRUNCATED_BEFORE_ANSWER" if reason == "MAX_TOKENS" else (
            "REFUSED" if reason in ("SAFETY", "PROHIBITED_CONTENT") else "EMPTY_RESPONSE")
        return {**out, "status": "error", "error": err}
    return {**out, "status": "ok"}


_OPENAI_LIKE_BASE = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com",
    "openrouter": OPENROUTER_URL,
}


async def _openai_like(client, spec, key, system, message, max_tokens, history=None):
    base = _OPENAI_LIKE_BASE[spec["provider"]]
    messages = ([{"role": "system", "content": system}] if system else []) + _turns(history, message)
    param = spec.get("token_param", "max_tokens")
    headers = {"Authorization": f"Bearer {key}"}
    if spec["provider"] == "openrouter":
        headers["X-Title"] = "OmniMed"
    budget = max(max_tokens, OPENAI_LIKE_MAX_TOKENS)
    payload = {"model": spec["id"], "messages": messages, param: budget}
    if spec["provider"] == "openrouter":
        payload["reasoning"] = {"max_tokens": REASONING_BUDGET}

    r = await _post(client, f"{base}/chat/completions", headers, payload)
    if r.status_code == 400 and "reasoning" in r.text.lower() and "reasoning" in payload:
        payload.pop("reasoning")      # a model that does not reason may reject the field
        r = await _post(client, f"{base}/chat/completions", headers, payload)
    # Newer OpenAI models reject max_tokens; swap the spelling once rather than
    # needing a registry change for every new model.
    if r.status_code == 400 and "max_completion_tokens" in r.text and param == "max_tokens":
        payload.pop(param, None)
        payload["max_completion_tokens"] = budget
        r = await _post(client, f"{base}/chat/completions", headers, payload)
    if r.status_code != 200:
        return _failure(r)
    data = r.json()
    choice = (data.get("choices") or [{}])[0]
    text = ((choice.get("message") or {}).get("content")) or ""
    u = data.get("usage") or {}
    out = {"text": text, "served_model": data.get("model"),
           "usage": _usage(u.get("prompt_tokens"), u.get("completion_tokens"))}
    if not text.strip():
        err = "TRUNCATED_BEFORE_ANSWER" if choice.get("finish_reason") == "length" else "EMPTY_RESPONSE"
        return {**out, "status": "error", "error": err}
    return {**out, "status": "ok"}


async def _cohere(client, spec, key, system, message, max_tokens, history=None):
    messages = ([{"role": "system", "content": system}] if system else []) + _turns(history, message)
    r = await _post(client, "https://api.cohere.com/v2/chat",
                    {"Authorization": f"Bearer {key}"},
                    {"model": spec["id"], "messages": messages,
                     "max_tokens": max(max_tokens, OPENAI_LIKE_MAX_TOKENS),
                     "thinking": {"type": "enabled", "token_budget": REASONING_BUDGET}})
    if r.status_code != 200:
        return _failure(r)
    data = r.json()
    content = (data.get("message") or {}).get("content") or []
    text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    tokens = (data.get("usage") or {}).get("tokens") or {}
    out = {"text": text, "served_model": spec["id"],
           "usage": _usage(tokens.get("input_tokens"), tokens.get("output_tokens"))}
    if not text.strip():
        # Command A reasons first, in "thinking" blocks that share the budget.
        err = "TRUNCATED_BEFORE_ANSWER" if data.get("finish_reason") == "MAX_TOKENS" else "EMPTY_RESPONSE"
        return {**out, "status": "error", "error": err}
    return {**out, "status": "ok"}


_CALLERS = {"anthropic": _anthropic, "google": _gemini, "cohere": _cohere,
            "openai": _openai_like, "groq": _openai_like,
            "deepseek": _openai_like, "openrouter": _openai_like}


async def call(key: str, message: str, system: str | None = None,
               max_tokens: int = 4096, timeout: float = TIMEOUT,
               client: httpx.AsyncClient | None = None, history: list | None = None) -> dict:
    spec = MODELS.get(key)
    base = {"model": key, "label": spec["label"] if spec else key}
    if not spec:
        return {**base, "status": "error", "error": "UNKNOWN_MODEL", "usage": _usage(), "seconds": 0}
    api_key = env.get_key(spec["provider"])
    if not api_key:
        return {**base, "status": "error", "error": "NO_API_KEY", "usage": _usage(), "seconds": 0}

    started = time.monotonic()
    own = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        res = await asyncio.wait_for(
            _CALLERS[spec["provider"]](client, spec, api_key, system, message, max_tokens, history),
            timeout=timeout)
    except asyncio.TimeoutError:
        res = {"status": "error", "error": "TIMEOUT"}
    except httpx.HTTPError as e:
        res = {"status": "error", "error": f"NETWORK_ERROR: {type(e).__name__}"}
    except Exception as e:  # a malformed provider reply must not sink the batch
        res = {"status": "error", "error": f"PROVIDER_ERROR: {str(e)[:160]}"}
    finally:
        if own:
            await client.aclose()
    res.setdefault("usage", _usage())
    return {**base, **res, "seconds": round(time.monotonic() - started, 1)}


async def call_many(keys: list[str], messages: dict, system: str | None = None,
                    max_tokens: int = 4096, timeout: float = TIMEOUT,
                    histories: dict | None = None) -> list[dict]:
    """Run every model concurrently; one failure never cancels the others.

    `messages` maps each model to its own message (the question, plus any
    papers or note that model was given); `histories` to its own earlier turns.
    """
    histories = histories or {}
    async with httpx.AsyncClient(timeout=timeout) as client:
        return list(await asyncio.gather(
            *[call(k, messages[k], system, max_tokens, timeout, client, histories.get(k))
              for k in keys]))


def judge_chain(scored_key: str, requested: str | None = None) -> list[str]:
    """Judges to try for one answer, never from the scored model's provider.

    The backend excludes only the scored model itself; this is stricter and
    excludes its whole provider, since a sibling model shares most of its
    training and its blind spots.
    """
    scored_provider = (MODELS.get(scored_key) or {}).get("provider")
    chain = []
    if requested and requested in MODELS and MODELS[requested]["provider"] != scored_provider:
        chain.append(requested)
    chain += [k for k in JUDGE_PREFERENCE
              if k not in chain and MODELS[k]["provider"] != scored_provider and available(k)]
    return chain
