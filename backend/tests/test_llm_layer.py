"""LLM layer: router offline tripwire, JSON extraction, cache-key stability,
analyst/synthesis flow with a fake transport, cost math, lens registry."""
import json

import pytest

from app.data.base import DiskTTLCache, OfflineError
from app.llm import analysts, router
from app.llm.cache import LLMCache, response_key
from app.llm.costs import CostMeter, price_call


# ---------------------------------------------------------------------------
# router
# ---------------------------------------------------------------------------
async def test_call_llm_raises_offline():
    with pytest.raises(OfflineError):
        await router.call_llm("system", "user", model="gemini-3.5-flash")


async def test_call_llm_no_key_reports_reason_not_silent_empty(monkeypatch):
    # No key means no branch ever performs a real fetch (guard_online is
    # only a flag check), so it's safe to lift the offline flag just for
    # this assertion — this exercises the "why did nothing happen" path
    # that used to return an unexplained empty string.
    monkeypatch.delenv("ALPHAMAXXIN_OFFLINE", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = await router.call_llm("system", "user", model="gemini-3.5-flash")
    assert result["text"] == ""
    assert "No LLM API key configured" in result["error"]


def test_semaphores():
    assert router.semaphore_for_model("claude-sonnet-4-6") is \
        router.semaphore_for_model("claude-opus-4-8")
    assert router.semaphore_for_model("gemini-3.5-flash") is not \
        router.semaphore_for_model("claude-sonnet-4-6")


def test_provider_routing_by_model_name():
    p = router._provider_for
    assert p("claude-sonnet-4-6", True, True, True) == "anthropic"
    assert p("claude-sonnet-4-6", False, True, True) == "anthropic"  # branch reports missing key
    # gpt models must reach OpenAI even when a Gemini key exists (was broken).
    assert p("gpt-4o-mini", False, True, True) == "openai"
    assert p("gpt-4o-mini", False, True, False) is None  # never sent to Gemini
    assert p("o3-mini", False, True, True) == "openai"
    assert p("gemini-3.5-flash", False, True, True) == "gemini"
    assert p("gemini-3.5-flash", False, False, True) is None
    # Unknown model id falls back to whatever is configured.
    assert p("mystery-model", False, True, False) == "gemini"
    assert p("mystery-model", False, False, True) == "openai"
    assert p("mystery-model", False, False, False) is None
    # Local models route to the OpenAI-compatible endpoint when configured.
    assert p("local/qwen3:14b", True, True, True, has_local=True) == "local"
    assert p("ollama/llama3.3", False, False, False, has_local=True) == "local"
    assert p("local/qwen3:14b", True, True, True, has_local=False) is None
    # With ONLY a local endpoint, unknown ids fall back to it.
    assert p("mystery-model", False, False, False, has_local=True) == "local"


# ---------------------------------------------------------------------------
# extract_json
# ---------------------------------------------------------------------------
def test_extract_json_variants():
    obj = {"stance": "neutral", "key_findings": ["a"]}
    direct = json.dumps(obj)
    fenced = f"Here you go:\n```json\n{direct}\n```\nthanks"
    embedded = f"Preamble text {direct} trailing text"
    assert analysts.extract_json(direct) == obj
    assert analysts.extract_json(fenced) == obj
    assert analysts.extract_json(embedded) == obj
    assert analysts.extract_json("no json here at all") is None
    assert analysts.extract_json("{broken: json") is None


# ---------------------------------------------------------------------------
# cache keys
# ---------------------------------------------------------------------------
def test_response_key_stable_and_sensitive():
    payload = {"b": 2, "a": 1}
    k1 = response_key("m", "sys", payload)
    k2 = response_key("m", "sys", {"a": 1, "b": 2})  # key order irrelevant
    assert k1 == k2
    assert response_key("m2", "sys", payload) != k1      # model changes key
    assert response_key("m", "sys2", payload) != k1      # prompt changes key
    assert response_key("m", "sys", {"a": 2, "b": 2}) != k1  # input changes key


# ---------------------------------------------------------------------------
# analyst flow with fake transport
# ---------------------------------------------------------------------------
def make_transport(response_obj, calls):
    async def transport(system_prompt, user_prompt, model):
        calls.append({"system": system_prompt, "user": user_prompt, "model": model})
        return {"text": json.dumps(response_obj), "model": model,
                "in_tokens": 1000, "out_tokens": 200}
    return transport


ANALYST_RESPONSE = {
    "stance": "supportive", "confidence": "high",
    "key_findings": ["RSI 28 oversold"], "narrative_md": "Looks washed out.",
}


async def test_run_analyst_parses_and_meters(tmp_path):
    calls = []
    meter = CostMeter(str(tmp_path / "costs.json"))
    out = await analysts.run_analyst(
        "technicals_options", {"technicals": {"AAA": {"rsi14": 28}}},
        model="gemini-3.5-flash", meter=meter, run_id="r1",
        transport=make_transport(ANALYST_RESPONSE, calls))
    assert out["ok"] is True
    assert out["stance"] == "supportive"
    assert out["key_findings"] == ["RSI 28 oversold"]
    assert out["cached"] is False
    assert "Technicals & Options Analyst" in calls[0]["system"]
    assert '"rsi14": 28' in calls[0]["user"]
    total = meter.run_total("r1")
    assert total["calls"] == 1 and total["in_tokens"] == 1000


async def test_run_analyst_cache_hit_skips_transport(tmp_path):
    calls = []
    cache = LLMCache(DiskTTLCache(root=tmp_path))
    transport = make_transport(ANALYST_RESPONSE, calls)
    payload = {"technicals": {"AAA": {"rsi14": 28}}}
    first = await analysts.run_analyst("macro", payload, "gemini-3.5-flash",
                                       cache=cache, transport=transport)
    second = await analysts.run_analyst("macro", payload, "gemini-3.5-flash",
                                        cache=cache, transport=transport)
    assert len(calls) == 1                      # second served from cache
    assert first["ok"] and second["ok"]
    assert second["cached"] is True


async def test_run_analyst_garbage_response_not_ok():
    async def transport(s, u, model):
        return {"text": "I refuse to answer in JSON.", "model": model,
                "in_tokens": 10, "out_tokens": 10}
    out = await analysts.run_analyst("risk", {}, "gemini-3.5-flash",
                                     transport=transport)
    assert out["ok"] is False
    assert out["narrative_md"] == ""
    assert "did not parse" in out["error"]


async def test_run_analyst_surfaces_transport_error():
    async def transport(s, u, model):
        return {"text": "", "model": model, "in_tokens": 0, "out_tokens": 0,
                "error": "no ANTHROPIC_API_KEY set in .env"}
    out = await analysts.run_analyst("risk", {}, "claude-sonnet-4-6",
                                     transport=transport)
    assert out["ok"] is False
    assert out["error"] == "no ANTHROPIC_API_KEY set in .env"


async def test_run_synthesis():
    calls = []
    response = {"markdown": "# Report\nVerdict: hold.",
                "recommendations": [{"ticker": "AAA", "action": "hold",
                                     "conviction": "medium", "rationale": "mixed"}]}
    out = await analysts.run_synthesis({"analysts": []}, "claude-sonnet-4-6",
                                       transport=make_transport(response, calls))
    assert out["ok"] is True
    assert out["markdown"].startswith("# Report")
    assert out["recommendations"][0]["ticker"] == "AAA"
    assert out["error"] is None


async def test_run_synthesis_surfaces_transport_error():
    async def transport(s, u, model):
        return {"text": "", "model": model, "in_tokens": 0, "out_tokens": 0,
                "error": "Claude API call failed: rate limited"}
    out = await analysts.run_synthesis({"analysts": []}, "claude-sonnet-4-6",
                                       transport=transport)
    assert out["ok"] is False
    assert out["error"] == "Claude API call failed: rate limited"


# ---------------------------------------------------------------------------
# costs
# ---------------------------------------------------------------------------
def test_price_call_known_and_unknown():
    priced = price_call("claude-sonnet-4-6", 1_000_000, 100_000)
    assert priced["usd"] == pytest.approx(3.00 + 1.50)
    assert priced["priced"] is True
    unknown = price_call("mystery-model", 1000, 1000)
    assert unknown["usd"] == 0.0 and unknown["priced"] is False


def test_cost_meter_totals_and_cached(tmp_path):
    meter = CostMeter(str(tmp_path / "costs.json"))
    meter.record("r1", "macro", "gemini-3.5-flash", 4000, 500)
    meter.record("r1", "risk", "gemini-3.5-flash", 3000, 400, cached=True)
    meter.record("r2", "synthesis", "claude-sonnet-4-6", 8000, 2000)
    r1 = meter.run_total("r1")
    assert r1["calls"] == 2 and r1["cached_calls"] == 1
    cached_entry = [c for c in meter._runs if c.get("cached")][0]
    assert cached_entry["usd"] == 0.0
    assert meter.totals()["calls"] == 3
    # Persisted across instances
    assert CostMeter(str(tmp_path / "costs.json")).totals()["calls"] == 3


# ---------------------------------------------------------------------------
# lens registry
# ---------------------------------------------------------------------------
def test_lens_status_reflects_feed_availability():
    feed_status = {"yahoo": True, "finnhub": True, "alphavantage": False,
                   "fred": True, "yfinance": True,
                   "altdata": True, "devdata": True}
    lenses = {l["id"]: l for l in analysts.lens_status(feed_status)}
    assert len(lenses) == 9  # all 9 promoted analysts; no disabled stubs left
    for analyst_id in analysts.ANALYSTS:
        if analyst_id in ("order_book", "ml_alpha"):
            # feeds down in this fixture (moomoo L2 / trained model)
            assert lenses[analyst_id]["enabled"] is False
        else:
            assert lenses[analyst_id]["enabled"] is True
    assert analysts.DISABLED_LENSES == {}  # machinery kept, currently empty




def test_lens_flips_on_when_feed_wired():
    feed_status = {"yahoo": True, "fred": True, "orderbook": True}
    lenses = {l["id"]: l for l in analysts.lens_status(feed_status)}
    assert lenses["order_book"]["enabled"] is True     # feed wired → lens on
    assert lenses["order_book"]["kind"] == "analyst"   # promoted, no longer a stub
    assert lenses["ml_alpha"]["enabled"] is False


def test_all_prompt_files_exist_and_load():
    for spec in list(analysts.ANALYSTS.values()) + list(analysts.DISABLED_LENSES.values()):
        text = analysts.load_prompt(spec["prompt_file"])
        assert len(text) > 200
    assert "JSON" in analysts.load_prompt("synthesis.md")
