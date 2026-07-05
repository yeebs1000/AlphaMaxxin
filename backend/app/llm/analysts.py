"""Domain analysts + synthesis + the lens registry.

Five analyst lenses interpret compact skills JSON; one synthesis call writes
the final report. Lenses whose required feeds aren't connected are DISABLED
(shown as such in UI/report, zero tokens) — never deleted; wiring a feed
flips them on. That includes the four v1 agents with no feasible free feed.
"""
import json
import re
from pathlib import Path

from . import router
from .cache import LLMCache, response_key

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# The active analyst lenses. required_feeds reference ProviderRegistry
# feed_status() keys — the lens runs if ANY of its feeds is up (they degrade
# gracefully), except where noted.
ANALYSTS = {
    "macro": {
        "name": "Macro Analyst",
        "prompt_file": "macro.md",
        "required_feeds": ["fred"],  # keyless, so effectively always on
    },
    "fundamentals": {
        "name": "Fundamentals Analyst",
        "prompt_file": "fundamentals.md",
        "required_feeds": ["yfinance", "finnhub"],
    },
    "technicals_options": {
        "name": "Technicals & Options Analyst",
        "prompt_file": "technicals_options.md",
        "required_feeds": ["yahoo"],
    },
    "news_catalysts": {
        "name": "News & Catalysts Analyst",
        "prompt_file": "news_catalysts.md",
        "required_feeds": ["finnhub", "alphavantage"],
    },
    "risk": {
        "name": "Risk Analyst",
        "prompt_file": "risk.md",
        "required_feeds": ["yahoo"],
    },
    # Promoted from DISABLED_LENSES once a real feed existed: moomoo's L2
    # order-book subscription (needs OpenD running + an L2 entitlement).
    # Automatically shows disabled again whenever that feed is down.
    "order_book": {
        "name": "Order Book & Liquidity Profiler",
        "prompt_file": "order_book.md",
        "required_feeds": ["orderbook"],
    },
}

# v1 agents with no feasible free feed — kept as ready-to-enable slots.
# Each names the feed a contributor would need to wire into app/data/ (and
# register in feed_status) to turn the lens on. Excluded from default
# report configs while disabled: unverifiable output can't raise conviction.
DISABLED_LENSES = {
    "alternative_data": {
        "name": "Alternative Data Analyst",
        "prompt_file": "lenses_disabled/alternative_data.md",
        "required_feeds": ["altdata"],
        "enable_hint": "wire a satellite/web alt-data provider (e.g. SimilarWeb) into app/data/",
    },
    "ml_alpha": {
        "name": "Machine Learning Alpha Extractor",
        "prompt_file": "lenses_disabled/ml_alpha.md",
        "required_feeds": ["ml_model"],
        "enable_hint": "add an offline-trained model artifact + inference provider",
    },
    "digital_footprint": {
        "name": "Digital Footprint & Developer Momentum Scanner",
        "prompt_file": "lenses_disabled/digital_footprint.md",
        "required_feeds": ["devdata"],
        "enable_hint": "wire GitHub/PyPI/npm stats providers into app/data/",
    },
}


def lens_status(feed_status: dict) -> list[dict]:
    """Every lens with its enabled/disabled state — drives UI and report
    transparency."""
    out = []
    for lens_id, spec in ANALYSTS.items():
        enabled = any(feed_status.get(f) for f in spec["required_feeds"])
        out.append({"id": lens_id, "name": spec["name"], "enabled": enabled,
                    "required_feeds": spec["required_feeds"], "kind": "analyst"})
    for lens_id, spec in DISABLED_LENSES.items():
        enabled = any(feed_status.get(f) for f in spec["required_feeds"])
        out.append({"id": lens_id, "name": spec["name"], "enabled": enabled,
                    "required_feeds": spec["required_feeds"], "kind": "lens",
                    "enable_hint": spec["enable_hint"]})
    return out


def load_prompt(prompt_file: str) -> str:
    return (PROMPTS_DIR / prompt_file).read_text(encoding="utf-8")


def extract_json(text: str):
    """Parse a JSON object from an LLM response — direct, fenced, or embedded."""
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except ValueError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            pass
    return None


async def run_analyst(role: str, payload: dict, model: str,
                      cache: LLMCache | None = None,
                      meter=None, run_id: str = "",
                      transport=router.call_llm) -> dict:
    """One analyst call: skills JSON in → structured finding out.
    Returns {role, ok, stance, confidence, key_findings, narrative_md,
    cached, model}. A failed/unparseable call returns ok=False — the
    synthesis prompt requires acknowledging the gap, not papering over it."""
    spec = ANALYSTS[role]
    system_prompt = load_prompt(spec["prompt_file"])
    user_prompt = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
    key = response_key(model, system_prompt, payload)

    cached_result = cache.get(key) if cache else None
    if cached_result is not None:
        result, was_cached = cached_result, True
    else:
        async with router.semaphore_for_model(model):
            result = await transport(system_prompt, user_prompt, model=model)
        was_cached = False
        if cache and result.get("text"):
            cache.put(key, result)
    if meter:
        meter.record(run_id, role, result.get("model", model),
                     result.get("in_tokens", 0), result.get("out_tokens", 0),
                     cached=was_cached)

    parsed = extract_json(result.get("text", "")) or {}
    ok = bool(parsed.get("narrative_md") or parsed.get("key_findings"))
    error = result.get("error") if not ok else None
    if not ok and not error and result.get("text"):
        error = "response did not parse as the expected JSON shape"
    return {
        "role": role,
        "name": spec["name"],
        "ok": ok,
        "stance": parsed.get("stance", "neutral"),
        "confidence": parsed.get("confidence", "low"),
        "key_findings": parsed.get("key_findings", []),
        "narrative_md": parsed.get("narrative_md", ""),
        "cached": was_cached,
        "model": result.get("model", model),
        "error": error,
    }


async def run_synthesis(payload: dict, model: str,
                        cache: LLMCache | None = None,
                        meter=None, run_id: str = "",
                        transport=router.call_llm) -> dict:
    """Final report writer: analyst findings + composite signals in →
    {ok, markdown, recommendations, cached, model}."""
    system_prompt = load_prompt("synthesis.md")
    user_prompt = json.dumps(payload, indent=1, ensure_ascii=False, default=str)
    key = response_key(model, system_prompt, payload)

    cached_result = cache.get(key) if cache else None
    if cached_result is not None:
        result, was_cached = cached_result, True
    else:
        async with router.semaphore_for_model(model):
            result = await transport(system_prompt, user_prompt, model=model)
        was_cached = False
        if cache and result.get("text"):
            cache.put(key, result)
    if meter:
        meter.record(run_id, "synthesis", result.get("model", model),
                     result.get("in_tokens", 0), result.get("out_tokens", 0),
                     cached=was_cached)

    parsed = extract_json(result.get("text", "")) or {}
    markdown = parsed.get("markdown", "")
    ok = bool(markdown)
    error = result.get("error") if not ok else None
    if not ok and not error and result.get("text"):
        error = "response did not parse as the expected JSON shape"
    return {
        "ok": ok,
        "markdown": markdown,
        "recommendations": parsed.get("recommendations", []),
        "cached": was_cached,
        "model": result.get("model", model),
        "error": error,
    }
