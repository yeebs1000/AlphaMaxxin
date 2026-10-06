"""Generate a synthetic report offline: python scripts/demo_report.py."""
import argparse
import asyncio
import datetime
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))
os.environ["ALPHAMAXXIN_OFFLINE"] = "1"


async def generate(output: Path) -> Path:
    # Reuse the existing no-network provider doubles, rather than a second framework.
    from backend.tests.fakes import make_registry, FakeYahoo, FakeFinnhub, FakeYFinance
    from app.llm.analysts import ANALYSTS
    from app.reports import store
    from app.reports.pipeline import run_report
    output.mkdir(parents=True, exist_ok=True)
    os.environ["ALPHAMAXXIN_LEDGER_FILE"] = str(output / "demo-ledger.json")
    os.environ["ALPHAMAXXIN_EQUITY_FILE"] = str(output / "demo-equity.json")
    closes = [80 + i * .08 + (i % 7) * .15 for i in range(260)]
    dates = [datetime.date(2025, 9, 1) + datetime.timedelta(days=i) for i in range(370)]
    stamps = [d.isoformat() for d in dates if d.weekday() < 5][:260]
    bars = {"closes": closes, "opens": closes, "highs": [c + 1 for c in closes],
            "lows": [c - 1 for c in closes], "volumes": [100_000] * 260, "timestamps": stamps}
    registry = make_registry(
        yahoo=FakeYahoo(ohlcv_data={"DEMO": bars, "^GSPC": bars},
                        quotes={"DEMO": {"price": closes[-1], "currency": "USD"}}),
        finnhub=FakeFinnhub(available=False),
        yfinance=FakeYFinance(fundamentals={"DEMO": {"ticker": "DEMO", "price": closes[-1],
                      "target_mean": 120, "rev_yoy": .1, "net_margin": .2, "sector": "Synthetic"}}))

    async def canned_transport(system_prompt, user_prompt, model):
        body = ({"markdown": "Synthetic example; no real company or model inference.",
                 "recommendations": [{"ticker": "DEMO", "action": "hold", "conviction": "low",
                                       "rationale": "Synthetic fixture for inspecting the report."}]}
                if "Synthesis" in system_prompt else
                {"stance": "neutral", "confidence": "low", "key_findings": ["Synthetic data only"],
                 "narrative_md": "No live research was performed."})
        return {"text": json.dumps(body), "model": "local/offline-fixture"}

    report_id = await run_report(registry, {"preset": "Lite", "target": {"kind": "tickers", "tickers": ["DEMO"]}},
                  lambda *args, **kwargs: None, reports_dir=str(output / "reports"),
                  settings={"models": {role: "local/offline-fixture" for role in [*ANALYSTS, "synthesis"]}},
                  transport=canned_transport)
    report = store.load_report(report_id, str(output / "reports"))
    assert report["sections"]["synthesis"]["ok"]
    assert report["sections"]["skills"]["recommendation_blocks"]["DEMO"]["bull_target"] == 120
    html = store.load_report_html(report_id, str(output / "reports"))
    html = re.sub(r'<img[^>]+src="https?://[^>]+>', '', html)
    demo_path = output / "offline-report.html"
    demo_path.write_text(html.replace("<body>", "<body><p>SYNTHETIC OFFLINE DEMO — no live data or AI inference.</p>"), encoding="utf-8")
    return demo_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data_store" / "demo")
    print(asyncio.run(generate(parser.parse_args().output.resolve())))
