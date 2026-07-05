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

# Friendly name → API model id (carried over from gui.py's MODEL_ID_MAP).
MODEL_ID_MAP = {
    "Gemini 2.5 Flash": "gemini-2.5-flash",
    "Gemini 3.0 Flash": "gemini-3-flash-preview",
    "Gemini 3.5 Flash": "gemini-3.5-flash",
    "Claude 3.5 Sonnet": "claude-3-5-sonnet-latest",
    "Claude 4.6 Sonnet": "claude-sonnet-4-6",
    "Claude 4.8 Opus": "claude-opus-4-8",
}

_PROVIDER_CONCURRENCY = {"claude": 4, "gemini": 12, "openai": 8}
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


async def call_llm(system_prompt: str, user_prompt: str,
                   model: str = DEFAULT_MODEL) -> dict:
    """Returns {text, model, in_tokens, out_tokens}. Empty text = failure
    (same semantics as v1)."""
    guard_online()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")

    if "claude" in model.lower():
        if not anthropic_key:
            return _result("", model, error="no ANTHROPIC_API_KEY set in .env")
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=anthropic_key)
        # One retry on transient 429/529 rather than dropping the analyst.
        for attempt in range(2):
            try:
                response = await client.messages.create(
                    model=model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=8192,
                    temperature=0.2,
                )
                if response and response.content:
                    text = "".join(b.text for b in response.content
                                   if b.type == "text").strip()
                    usage = getattr(response, "usage", None)
                    return _result(text, model,
                                   getattr(usage, "input_tokens", 0),
                                   getattr(usage, "output_tokens", 0),
                                   error=None if text else "Claude returned an empty response")
                return _result("", model, error="Claude returned no content")
            except Exception as e:
                status = getattr(e, "status_code", None)
                if attempt == 0 and status in (429, 529):
                    await asyncio.sleep(2.0)
                    continue
                print(f"Claude API call failed: {e}.", file=sys.stderr)
                return _result("", model, error=f"Claude API call failed: {e}")
        return _result("", model, error="Claude API call failed after retry")

    if gemini_key:
        try:
            import google.genai as genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            # Sync client — run in a thread so concurrent analysts don't serialize.
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                ),
            )
            if response and response.text:
                meta = getattr(response, "usage_metadata", None)
                return _result(response.text.strip(), model,
                               getattr(meta, "prompt_token_count", 0) or 0,
                               getattr(meta, "candidates_token_count", 0) or 0)
            return _result("", model, error="Gemini returned an empty response "
                           f"(model '{model}' — check it's a valid, available model id)")
        except Exception as e:
            print(f"Gemini API call failed: {e}.", file=sys.stderr)
            return _result("", model, error=f"Gemini API call failed: {e}")

    if openai_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            openai_model = model if "gpt" in model else "gpt-4o-mini"
            response = await asyncio.to_thread(
                client.chat.completions.create,
                model=openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            if response and response.choices:
                usage = getattr(response, "usage", None)
                return _result(response.choices[0].message.content.strip(),
                               openai_model,
                               getattr(usage, "prompt_tokens", 0) or 0,
                               getattr(usage, "completion_tokens", 0) or 0)
            return _result("", openai_model, error="OpenAI returned no choices")
        except Exception as e:
            print(f"OpenAI API call failed: {e}.", file=sys.stderr)
            return _result("", model, error=f"OpenAI API call failed: {e}")

    return _result("", model, error="No LLM API key configured "
                   "(set ANTHROPIC_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in .env)")
