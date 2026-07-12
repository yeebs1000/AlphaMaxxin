"""The 9 report presets — named configurations of skills + analyst lenses,
carrying over the intent, market_scan flags, and region scoping of the v1
presets (gui.py:211-368). `skills` controls which deterministic engines run;
`analysts` which LLM lenses interpret them; synthesis always runs last."""

PRESETS = {
    "Lite": {
        "description": "Fast core read of your portfolio — technicals, fundamentals, risk.",
        "skills": ["technicals", "fundamentals", "risk", "performance", "signals"],
        "analysts": ["fundamentals", "technicals_options", "risk"],
        "market_scan": False,
        "regions": None,
    },
    "Opportunist": {
        "description": "Scan the broad market for new high-conviction setups.",
        "skills": ["screener", "technicals", "fundamentals", "news", "catalysts",
                   "insiders", "signals", "risk", "alt_data"],
        "analysts": ["fundamentals", "technicals_options", "news_catalysts",
                     "risk", "alternative_data"],
        "market_scan": True,
        "regions": None,
    },
    "Macro Pulse": {
        "description": "Global macro, rates, FX, market review, and supply-chain flow.",
        "skills": ["macro", "market_review", "supply_chain", "news"],
        "analysts": ["macro", "news_catalysts"],
        "market_scan": True,
        "regions": None,
    },
    "Portfolio Medic": {
        "description": "Full-team health check on your existing holdings.",
        "skills": ["technicals", "fundamentals", "risk", "portfolio_construction",
                   "performance", "signals", "order_book", "dividends",
                   "macro", "news", "catalysts", "insiders", "ml_alpha",
                   "alt_data", "digital_footprint"],
        "analysts": ["macro", "fundamentals", "technicals_options",
                     "news_catalysts", "risk", "order_book", "ml_alpha",
                     "alternative_data", "digital_footprint"],
        "market_scan": False,
        "regions": None,
    },
    "Dragon Watch": {
        "description": "China/HK focus — HKEX candidates plus your China exposure.",
        "skills": ["macro", "screener", "technicals", "fundamentals", "news",
                   "signals", "risk"],
        "analysts": ["macro", "fundamentals", "technicals_options",
                     "news_catalysts", "risk"],
        "market_scan": True,
        "regions": ["HK"],
    },
    "Sakura Signal": {
        "description": "Japan focus — Tokyo-listed candidates.",
        "skills": ["macro", "screener", "technicals", "fundamentals", "news",
                   "signals", "risk"],
        "analysts": ["macro", "fundamentals", "technicals_options",
                     "news_catalysts", "risk"],
        "market_scan": True,
        "regions": ["JP"],
    },
    "Kimchi Premium": {
        "description": "Korea focus — KOSPI/KOSDAQ candidates.",
        "skills": ["macro", "screener", "technicals", "fundamentals", "news",
                   "signals", "risk"],
        "analysts": ["macro", "fundamentals", "technicals_options",
                     "news_catalysts", "risk"],
        "market_scan": True,
        "regions": ["KR"],
    },
    "Frontier Run": {
        "description": "Emerging/rest-of-world focus across all regions.",
        "skills": ["macro", "screener", "technicals", "fundamentals", "news",
                   "signals", "risk"],
        "analysts": ["macro", "fundamentals", "technicals_options",
                     "news_catalysts", "risk"],
        "market_scan": True,
        "regions": None,
    },
    "Quant Lab": {
        "description": "Pure quant scan — strategies, signals, depth, ML alpha, and risk.",
        "skills": ["screener", "technicals", "strategies", "signals", "risk",
                   "options_math", "order_book", "ml_alpha"],
        "analysts": ["technicals_options", "risk", "order_book", "ml_alpha"],
        "market_scan": True,
        "regions": None,
    },
    "Insider Edge": {
        "description": "Corporate insider filings, congressional trades, news, and catalysts.",
        "skills": ["politician_trades", "insiders", "news", "catalysts", "risk"],
        "analysts": ["news_catalysts", "risk"],
        "market_scan": True,
        "regions": None,
    },
}

DEFAULT_PRESET = "Lite"


def get_preset(name: str) -> dict:
    preset = PRESETS.get(name)
    if preset is None:
        raise KeyError(f"unknown preset '{name}' — valid: {sorted(PRESETS)}")
    return {"name": name, **preset}


def list_presets() -> list[dict]:
    return [{"name": name, **spec} for name, spec in PRESETS.items()]
