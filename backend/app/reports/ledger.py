"""Conviction ledger — records every actionable recommendation a report makes
and scores it against real prices later, so "high conviction" becomes a
measured hit rate instead of a vibe.

One JSON file (data_store/ledger.json) holds two things:
- entries: one per actionable recommendation (buy/accumulate/sell/reduce),
  joined with that ticker's recommendation_block for price/stop/target.
- levels: latest computed {price_at_rec, bear_stop, base_target} per ticker —
  the watcher's O(1) lookup for "what levels does the latest analysis give
  this holding" (the report index has no per-ticker view).

Scoring is close-basis and buys-only for hit rate: intraday touches aren't
visible to cached quotes, and sell/reduce calls just track return until they
expire. # ponytail: upgrade to intraday-low/short-side scoring if it matters.
"""
import datetime
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_FILE = str(REPO_ROOT / "data_store" / "ledger.json")


def _path(file_path=None) -> str:
    # Env override so the offline test suite (which runs the full pipeline,
    # ledger hook included) never writes the real data_store/ledger.json.
    return file_path or os.environ.get("ALPHAMAXXIN_LEDGER_FILE") or LEDGER_FILE

_ACTIONABLE = {"buy", "accumulate", "sell", "reduce"}
_EXPIRE_DAYS = 90


def _load(file_path=None) -> dict:
    path = _path(file_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"entries": data.get("entries", []), "levels": data.get("levels", {})}
    except (OSError, ValueError):
        return {"entries": [], "levels": {}}


def _save(data: dict, file_path=None) -> None:
    path = _path(file_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)


def record(report: dict, file_path=None) -> int:
    """Append the report's actionable recommendations and refresh the levels
    map. Failure-soft: recording must never sink a report run. Returns the
    number of entries added."""
    try:
        report_id = report.get("id", "")
        date = (report.get("created_at") or "")[:10]
        blocks = (report.get("sections", {}).get("skills", {})
                  .get("recommendation_blocks") or {})
        recs = (report.get("sections", {}).get("synthesis", {})
                .get("recommendations") or [])

        data = _load(file_path)
        existing = {e["id"] for e in data["entries"]}
        added = 0
        for rec in recs:
            ticker = rec.get("ticker")
            block = blocks.get(ticker)
            if (not ticker or not block
                    or rec.get("action") not in _ACTIONABLE
                    or f"{report_id}:{ticker}" in existing):
                continue
            data["entries"].append({
                "id": f"{report_id}:{ticker}",
                "date": date,
                "report_id": report_id,
                "preset": report.get("preset"),
                "ticker": ticker,
                "action": rec.get("action"),
                "conviction": rec.get("conviction", "low"),
                "size": rec.get("size"),
                "price_at_rec": block.get("current_price"),
                "bear_stop": block.get("bear_stop"),
                "base_target": block.get("base_target"),
                "status": "open",
            })
            added += 1
        for ticker, block in blocks.items():
            data["levels"][ticker] = {
                "date": date,
                "price_at_rec": block.get("current_price"),
                "bear_stop": block.get("bear_stop"),
                "base_target": block.get("base_target"),
                "report_id": report_id,
            }
        _save(data, file_path)
        return added
    except Exception as e:  # noqa: BLE001
        print(f"[ledger] record failed (report run unaffected): {e}")
        return 0


def score(quote_fn, file_path=None, today: datetime.date | None = None) -> dict:
    """Resolve open entries against current prices. quote_fn(ticker) → quote
    dict or None. Buys resolve on target/stop/expiry; sells/reduces on expiry
    only. Returns the updated ledger data."""
    today = today or datetime.date.today()
    data = _load(file_path)
    for e in data["entries"]:
        if e["status"] != "open" or not e.get("price_at_rec"):
            continue
        quote = quote_fn(e["ticker"])
        price = (quote or {}).get("price")
        if not price:
            continue
        e["last_price"] = price
        e["return_pct"] = round((price - e["price_at_rec"]) / e["price_at_rec"] * 100, 2)
        age = (today - datetime.date.fromisoformat(e["date"])).days if e.get("date") else 0
        if e["action"] in ("buy", "accumulate"):
            if e.get("base_target") and price >= e["base_target"]:
                e["status"] = "target"
            elif e.get("bear_stop") and price <= e["bear_stop"]:
                e["status"] = "stopped"
            elif age > _EXPIRE_DAYS:
                e["status"] = "expired"
        elif age > _EXPIRE_DAYS:
            e["status"] = "expired"
        if e["status"] != "open":
            e["resolved_date"] = today.isoformat()
    _save(data, file_path)
    return data


def summary(file_path=None) -> dict:
    """Calibration stats per conviction level. Hit rate = targets vs stops
    (buys only); expired entries contribute to avg return but not hit rate."""
    data = _load(file_path)
    by_conv: dict = {}
    for e in data["entries"]:
        c = by_conv.setdefault(e.get("conviction", "low"),
                               {"n": 0, "resolved": 0, "target_hits": 0,
                                "stop_hits": 0, "returns": []})
        c["n"] += 1
        if e["status"] != "open":
            c["resolved"] += 1
            if "return_pct" in e:
                c["returns"].append(e["return_pct"])
            if e["status"] == "target":
                c["target_hits"] += 1
            elif e["status"] == "stopped":
                c["stop_hits"] += 1
    out = {}
    for conv, c in by_conv.items():
        decided = c["target_hits"] + c["stop_hits"]
        out[conv] = {
            "n": c["n"], "resolved": c["resolved"],
            "target_hits": c["target_hits"], "stop_hits": c["stop_hits"],
            "hit_rate": round(c["target_hits"] / decided, 2) if decided else None,
            "avg_return_pct": round(sum(c["returns"]) / len(c["returns"]), 2)
                              if c["returns"] else None,
        }
    return {"by_conviction": out,
            "open": sum(1 for e in data["entries"] if e["status"] == "open"),
            "total": len(data["entries"])}
