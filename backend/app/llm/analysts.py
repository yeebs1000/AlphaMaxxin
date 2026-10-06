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

# Output-token ceilings. Analysts return one compact finding (a short
# key_findings list + a 100-250 word narrative ≈ 600 tokens) — 1500 is
# generous headroom while still hard-capping a runaway generation, the main
# thing that pushes an analyst call toward the timeout. Synthesis writes the
# whole report, so it keeps the roomier default.
ANALYST_MAX_TOKENS = 1500
SYNTHESIS_MAX_TOKENS = 8192


def _bound_transport(json_mode: bool, max_output_tokens: int):
    """Default transport = call_llm with the JSON-mode + token-cap contract
    baked in, so run_analyst/run_synthesis apply it without every injected
    test fake having to grow the two extra kwargs."""
    async def transport(system_prompt: str, user_prompt: str, model: str) -> dict:
        return await router.call_llm(system_prompt, user_prompt, model=model,
                                     json_mode=json_mode,
                                     max_output_tokens=max_output_tokens)
    return transport


def _synthesis_errors(parsed, payload: dict) -> list[str]:
    if not isinstance(parsed, dict) or not isinstance(parsed.get("markdown"), str) \
            or not parsed["markdown"].strip() or not isinstance(parsed.get("recommendations"), list):
        return ["response did not parse as the expected JSON shape"]
    errors, seen = [], set()
    blocks = payload.get("recommendation_blocks") or {}
    composites = payload.get("composites") or {}
    summary = payload.get("summary") or {}
    universe = set(blocks) | set(composites) | set(summary.get("tickers") or [])
    universe.update(h["ticker"] for h in summary.get("holdings", []) if h.get("ticker"))
    succeeded = [a for a in payload.get("analysts", []) if a.get("ok")]
    stances = {a.get("stance") for a in succeeded}
    conflict = bool(stances & {"supportive", "bullish"}) and bool(stances & {"cautious", "headwind", "bearish"})
    ranks = {"none": 0, "low": 1, "medium": 2, "high": 3}
    for rec in parsed["recommendations"]:
        if not isinstance(rec, dict) or set(rec) - {"ticker", "action", "conviction", "size", "rationale"}:
            errors.append("recommendation has unsupported fields or shape")
            continue
        ticker = rec.get("ticker")
        if not isinstance(ticker, str) or ticker not in universe or ticker in seen:
            errors.append("recommendation ticker is unknown or duplicated")
            continue
        seen.add(ticker)
        action, conviction = rec.get("action"), rec.get("conviction")
        if not isinstance(action, str) or not isinstance(conviction, str):
            errors.append(f"{ticker}: action and conviction must be strings")
            continue
        if action not in {"buy", "accumulate", "hold", "reduce", "sell"}:
            errors.append(f"{ticker}: invalid action")
        if conviction not in ranks or conviction == "none":
            errors.append(f"{ticker}: invalid conviction")
        limit = ranks.get(composites.get(ticker, {}).get("conviction", "low"), 1)
        if len(succeeded) < 3 or conflict:
            limit = min(limit, 2)
        if ranks.get(conviction, 0) > limit:
            errors.append(f"{ticker}: conviction exceeds evidence coverage")
        if not isinstance(rec.get("rationale", ""), str):
            errors.append(f"{ticker}: invalid rationale")
        block = blocks.get(ticker) or {}
        if action in {"buy", "accumulate"}:
            if summary.get("errors"):
                errors.append(f"{ticker}: portfolio valuation is incomplete; allocation withheld")
            from ..data.base import to_number
            price, stop, base, bull = [to_number(block.get(k)) for k in
                                      ("current_price", "bear_stop", "base_target", "bull_target")]
            valid_levels = all(v is not None for v in (price, stop, base, bull)) \
                and 0 < stop < price < base <= bull
            if not valid_levels or block.get("red_lines") or block.get("size_tier", "Pass") == "Pass" \
                    or conviction not in {"high", "medium"}:
                errors.append(f"{ticker}: computed inputs veto a buy")
            if rec.get("size") != block.get("size_tier"):
                errors.append(f"{ticker}: size disagrees with computed tier")
        elif "size" in rec and (not isinstance(rec["size"], str) or rec["size"] not in {"Full", "Half", "Starter", "Pass"}):
            errors.append(f"{ticker}: invalid size")
    return errors


def recommendation_markdown(payload: dict, recommendations: list[dict]) -> str:
    """Authoritative tables use computed fields; free model prose is kept separately."""
    lines = ["# Report", "", "## Recommendations", "",
             "| Ticker | Action | Conviction | Computed buy tier |",
             "| --- | --- | --- | --- |"]
    blocks = payload.get("recommendation_blocks") or {}
    for rec in recommendations:
        block = blocks.get(rec["ticker"]) or {}
        tier = f"{block.get('size_tier', 'Pass')} ({block.get('suggested_weight_pct', 0)}%)"
        lines.append(f"| {rec['ticker']} | {rec['action']} | {rec['conviction']} | {tier} |")
    if not recommendations:
        lines.append("\nNo validated recommendations this run.")
    for ticker, b in blocks.items():
        lines += ["", f"**{ticker}** — Entry {b['entry_range'][0]}–{b['entry_range'][1]} | "
                  f"Base {b['base_target']} | Bull {b['bull_target']} | Stop {b['bear_stop']} | "
                  f"R:R {b['risk_reward_base']} | Size: {b['size_tier']} {b['suggested_weight_pct']}% "
                  f"(source: {b['target_source']}; native quote currency)"]
        if b.get("red_lines"):
            lines.append("Buy veto: " + "; ".join(b["red_lines"]))
    lines += ["", "Sizing tiers are fixed research heuristics, not optimized allocations.",
              "Model commentary is stored separately and is not fact-verified."]
    if payload.get("lens_status"):
        lines += ["", "## Coverage", ""]
        for lens in payload["lens_status"]:
            status = ("ran" if lens.get("ran") else "feed disabled" if not lens.get("enabled")
                      else "not part of this preset" if not lens.get("in_preset")
                      else "skipped: insufficient target data")
            lines.append(f"- {lens['name']}: {status}")
    return "\n".join(lines)


ANALYST_TRANSPORT = _bound_transport(True, ANALYST_MAX_TOKENS)
SYNTHESIS_TRANSPORT = _bound_transport(True, SYNTHESIS_MAX_TOKENS)

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
    # Promoted from DISABLED_LENSES once a real feed existed: an offline-trained
    # scikit-learn model artifact (data/ml_model.py). Shows disabled again
    # whenever no artifact is present (i.e. before the user runs training).
    "ml_alpha": {
        "name": "Machine Learning Alpha Extractor",
        "prompt_file": "ml_alpha.md",
        "required_feeds": ["ml_model"],
    },
    # Promoted 2026-07: attention/demand proxies from official keyless APIs
    # (Wikipedia pageviews, iTunes, Greenhouse boards) — see data/altdata.py.
    "alternative_data": {
        "name": "Alternative Data Analyst",
        "prompt_file": "alternative_data.md",
        "required_feeds": ["altdata"],
    },
    # Promoted 2026-07: GitHub/npm/PyPI/Docker developer mindshare — see
    # data/devdata.py.
    "digital_footprint": {
        "name": "Digital Footprint & Developer Momentum Scanner",
        "prompt_file": "digital_footprint.md",
        "required_feeds": ["devdata"],
    },
}

# Ready-to-enable slots for future lenses with no feasible free feed yet —
# empty since the last two v1 holdouts were promoted above, but the registry
# machinery stays (lenses get disabled here, never deleted).
DISABLED_LENSES: dict = {}


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
    """Parse a JSON object from an LLM response — direct, fenced, or embedded.
    Local reasoning models (qwen3 etc.) prepend <think>…</think> blocks;
    strip them so the JSON that follows still parses."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
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
                      transport=ANALYST_TRANSPORT) -> dict:
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
    if meter:
        meter.record(run_id, role, result.get("model", model),
                     result.get("in_tokens", 0), result.get("out_tokens", 0),
                     cached=was_cached)

    parsed = extract_json(result.get("text", ""))
    valid = (isinstance(parsed, dict)
             and isinstance(parsed.get("narrative_md", ""), str)
             and isinstance(parsed.get("key_findings", []), list)
             and all(isinstance(f, str) for f in parsed.get("key_findings", []))
             and isinstance(parsed.get("stance", "neutral"), str)
             and parsed.get("stance", "neutral") in {"supportive", "neutral", "cautious", "headwind", "bullish", "bearish"}
             and isinstance(parsed.get("confidence", "low"), str)
             and parsed.get("confidence", "low") in {"low", "medium", "high"})
    parsed = parsed if valid else {}
    ok = bool(parsed.get("narrative_md") or parsed.get("key_findings")) and not result.get("error")
    if ok and cache and not was_cached:
        cache.put(key, result)
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
                        transport=SYNTHESIS_TRANSPORT) -> dict:
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
    if meter:
        meter.record(run_id, "synthesis", result.get("model", model),
                     result.get("in_tokens", 0), result.get("out_tokens", 0),
                     cached=was_cached)

    parsed = extract_json(result.get("text", ""))
    errors = _synthesis_errors(parsed, payload)
    ok = not errors and not result.get("error")
    parsed = parsed if ok else {}
    if ok and cache and not was_cached:
        cache.put(key, result)
    error = result.get("error") if not ok else None
    if not ok and not error and result.get("text"):
        error = "; ".join(errors)
    return {
        "ok": ok,
        "markdown": recommendation_markdown(payload, parsed["recommendations"]) if ok else "",
        "commentary_md": parsed.get("markdown", ""),
        "recommendations": parsed.get("recommendations", []),
        "contract_errors": errors,
        "cached": was_cached,
        "model": result.get("model", model),
        "error": error,
    }
