"""LLM router — port of runner.call_llm with per-provider semaphores and
MODEL_ID_MAP, extended to report token usage for the cost meter. Guarded by
the same offline tripwire as the data providers: with ALPHAMAXXIN_OFFLINE=1
any real LLM call raises. Tests use a fake transport instead.
"""
import asyncio
import os
import sys

from ..data.base import guard_online

DEFAULT_MODEL = "gemini-3.5-flash"

# Hard ceiling on any single provider call. Without one, a stalled request
# (e.g. a 503 storm) hangs forever — a scheduled watcher run once sat stuck
# for an hour+ blocking every subsequent 15-minute cycle.
REQUEST_TIMEOUT_S = 120.0


def _provider_for(model: str, has_anthropic: bool, has_gemini: bool,
                  has_openai: bool, has_local: bool = False) -> str | None:
    """Route by MODEL NAME first, key presence second. (Key-presence-only
    routing sent gpt-* ids to the Gemini client whenever a Gemini key
    existed, making OpenAI unreachable.)

    "local/<model>" or "ollama/<model>" ids route to the OpenAI-compatible
    endpoint named by LOCAL_LLM_BASE_URL (Ollama, LM Studio, llama.cpp
    server, vLLM — all speak that protocol)."""
    m = (model or "").lower()
    if m.startswith(("local/", "ollama/")):
        return "local" if has_local else None
    if "claude" in m:
        return "anthropic"
    if "gpt" in m or m.startswith("o1") or m.startswith("o3"):
        return "openai" if has_openai else None
    if "gemini" in m:
        return "gemini" if has_gemini else None
    # Unknown model id — fall back to whichever provider is configured.
    if has_gemini:
        return "gemini"
    if has_openai:
        return "openai"
    if has_local:
        return "local"
    return None

# local: consumer GPUs serve one request well; two queue without thrashing.
_PROVIDER_CONCURRENCY = {"claude": 4, "gemini": 12, "openai": 8, "local": 2}
_DEFAULT_CONCURRENCY = 6
_provider_semaphores: dict[str, asyncio.Semaphore] = {
    provider: asyncio.Semaphore(limit)
    for provider, limit in _PROVIDER_CONCURRENCY.items()
}


def semaphore_for_model(model: str) -> asyncio.Semaphore:
    model_lower = (model or "").lower()
    for provider, semaphore in _provider_semaphores.items():
        if provider in model_lower:
            return semaphore
    return _provider_semaphores.setdefault(
        "_default", asyncio.Semaphore(_DEFAULT_CONCURRENCY))


def _result(text: str, model: str, in_tokens: int = 0, out_tokens: int = 0,
           error: str | None = None) -> dict:
    return {"text": text, "model": model,
            "in_tokens": in_tokens, "out_tokens": out_tokens, "error": error}


def _openai_kwargs(model: str, system_prompt: str, user_prompt: str,
                   json_mode: bool, max_output_tokens: int | None) -> dict:
    """chat.completions.create kwargs for the OpenAI + local (OpenAI-compatible)
    branches — response_format/max_tokens only when asked, so an older server
    or a model that rejects them isn't handed an unsupported field. json_object
    mode needs the word 'json' in the prompt, which the lens prompts satisfy."""
    kwargs = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.2,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_output_tokens:
        kwargs["max_tokens"] = max_output_tokens
    return kwargs


async def call_llm(system_prompt: str, user_prompt: str,
                   model: str = DEFAULT_MODEL, json_mode: bool = False,
                   max_output_tokens: int | None = None) -> dict:
    """Returns {text, model, in_tokens, out_tokens}. Empty text = failure
    (same semantics as v1).

    json_mode asks the provider for valid JSON directly (Gemini
    response_mime_type, OpenAI/local response_format=json_object) — the
    lenses already prompt for a fixed JSON shape, so this removes the
    fences/preamble a free-form model adds and keeps output parseable.
    max_output_tokens caps generation: the analysts don't need long prose,
    and an uncapped narrative is the main thing that stretches a call toward
    the timeout. extract_json still runs as the safety net."""
    guard_online()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    local_base_url = os.environ.get("LOCAL_LLM_BASE_URL", "").strip()

    provider = _provider_for(model, bool(anthropic_key), bool(gemini_key),
                             bool(openai_key), bool(local_base_url))

    try:
        if provider == "local":
            # Any OpenAI-compatible local server: Ollama (http://127.0.0.1:11434/v1),
            # LM Studio (:1234/v1), llama.cpp server, vLLM. Free — the cost
            # meter prices these at $0. Longer timeout: local inference on
            # consumer hardware is slower than cloud.
            from openai import OpenAI
            client = OpenAI(base_url=local_base_url,
                            api_key=os.environ.get("LOCAL_LLM_API_KEY", "local"),
                            timeout=REQUEST_TIMEOUT_S * 3, max_retries=0)
            local_model = model.split("/", 1)[1] if "/" in model else model
            local_kwargs = _openai_kwargs(local_model, system_prompt, user_prompt,
                                          json_mode, max_output_tokens)
            response = await asyncio.wait_for(
                asyncio.to_thread(client.chat.completions.create, **local_kwargs),
                timeout=REQUEST_TIMEOUT_S * 3)
            if response and response.choices:
                usage = getattr(response, "usage", None)
                return _result(response.choices[0].message.content.strip(),
                               model,
                               getattr(usage, "prompt_tokens", 0) or 0,
                               getattr(usage, "completion_tokens", 0) or 0)
            return _result("", model, error="local LLM returned no choices")

        if provider == "anthropic":
            if not anthropic_key:
                return _result("", model, error="no ANTHROPIC_API_KEY set in .env")
            from anthropic import AsyncAnthropic
            # SDK handles transient 429/5xx retries; timeout bounds each attempt.
            client = AsyncAnthropic(api_key=anthropic_key,
                                    timeout=REQUEST_TIMEOUT_S, max_retries=2)
            # Claude's Messages API has no json_mode flag — the prompt-driven
            # JSON + extract_json path carries it; the cap still applies.
            response = await asyncio.wait_for(
                client.messages.create(
                    model=model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=max_output_tokens or 8192,
                    temperature=0.2,
                ),
                timeout=REQUEST_TIMEOUT_S * 3)  # belt over the SDK's retries
            if response and response.content:
                text = "".join(b.text for b in response.content
                               if b.type == "text").strip()
                usage = getattr(response, "usage", None)
                return _result(text, model,
                               getattr(usage, "input_tokens", 0),
                               getattr(usage, "output_tokens", 0),
                               error=None if text else "Claude returned an empty response")
            return _result("", model, error="Claude returned no content")

        if provider == "gemini":
            import google.genai as genai
            from google.genai import types
            try:  # http_options timeout is in ms; tolerate older SDKs
                client = genai.Client(api_key=gemini_key, http_options=types.HttpOptions(
                    timeout=int(REQUEST_TIMEOUT_S * 1000)))
            except TypeError:
                client = genai.Client(api_key=gemini_key)
            gem_cfg = {"system_instruction": system_prompt, "temperature": 0.2}
            if max_output_tokens:
                gem_cfg["max_output_tokens"] = max_output_tokens
            if json_mode:
                gem_cfg["response_mime_type"] = "application/json"
            # Sync client — thread keeps concurrent analysts parallel; wait_for
            # guarantees the caller never hangs even if the SDK stalls.
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.models.generate_content,
                    model=model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(**gem_cfg),
                ),
                timeout=REQUEST_TIMEOUT_S)
            if response and response.text:
                meta = getattr(response, "usage_metadata", None)
                return _result(response.text.strip(), model,
                               getattr(meta, "prompt_token_count", 0) or 0,
                               getattr(meta, "candidates_token_count", 0) or 0)
            return _result("", model, error="Gemini returned an empty response "
                           f"(model '{model}' — check it's a valid, available model id)")

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(api_key=openai_key,
                            timeout=REQUEST_TIMEOUT_S, max_retries=1)
            openai_model = model if ("gpt" in model or model.startswith("o")) \
                else "gpt-4o-mini"
            oai_kwargs = _openai_kwargs(openai_model, system_prompt, user_prompt,
                                        json_mode, max_output_tokens)
            response = await asyncio.wait_for(
                asyncio.to_thread(client.chat.completions.create, **oai_kwargs),
                timeout=REQUEST_TIMEOUT_S * 2)
            if response and response.choices:
                usage = getattr(response, "usage", None)
                return _result(response.choices[0].message.content.strip(),
                               openai_model,
                               getattr(usage, "prompt_tokens", 0) or 0,
                               getattr(usage, "completion_tokens", 0) or 0)
            return _result("", openai_model, error="OpenAI returned no choices")

    except asyncio.TimeoutError:
        print(f"LLM call timed out after {REQUEST_TIMEOUT_S:.0f}s "
              f"({provider}/{model}).", file=sys.stderr)
        return _result("", model, error=f"{provider} call timed out")
    except Exception as e:
        print(f"{provider} API call failed: {e}.", file=sys.stderr)
        return _result("", model, error=f"{provider} API call failed: {e}")

    return _result("", model, error="No LLM API key configured for this model "
                   "(set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in .env)")
