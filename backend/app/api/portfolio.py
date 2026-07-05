from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import portfolio as pf
from ..data.live_quote import live_quote, live_ohlcv
from ..skills import performance, signals, technicals, fx as fx_skill
from .deps import get_registry

router = APIRouter(tags=["portfolio"])


class Holding(BaseModel):
    company: str
    ticker: str
    quantity: float
    cost_price: float = 0.0
    currency: str = "USD"


def _quotes_for(registry, holdings: list[dict]) -> dict:
    quotes = {}
    for h in holdings:
        quote = live_quote(h["ticker"], registry.yahoo)
        if quote:
            quotes[h["ticker"]] = quote
    return quotes


def _fx_rates(registry, holdings: list[dict]) -> dict:
    rates = {"USD": 1.0}
    for ccy in {h.get("currency", "USD") for h in holdings}:
        if ccy != "USD":
            rate = registry.yahoo.fx_rate(ccy)
            if rate:
                rates[ccy] = rate
    return rates


@router.get("/portfolio")
def get_portfolio():
    return {"holdings": pf.parse_portfolio()}


@router.put("/portfolio")
def put_portfolio(holdings: list[Holding], registry=Depends(get_registry)):
    dicts = [h.model_dump() for h in holdings]
    pf.save_portfolio(dicts, quotes=_quotes_for(registry, dicts))
    return {"holdings": pf.parse_portfolio()}


@router.post("/portfolio/sync")
def sync_portfolio(registry=Depends(get_registry)):
    result = pf.sync_from_brokers()
    if result["success"]:
        # Rewrite with live prices now that we know the merged holdings.
        pf.save_portfolio(result["holdings"],
                          quotes=_quotes_for(registry, result["holdings"]))
    return result


@router.get("/portfolio/summary")
def portfolio_summary(registry=Depends(get_registry)):
    holdings = pf.parse_portfolio()
    quotes = _quotes_for(registry, holdings)
    benchmark = registry.yahoo.quote("^GSPC")
    return performance.portfolio_summary(
        holdings, quotes, fx_rates=_fx_rates(registry, holdings),
        benchmark_quote=benchmark)


@router.get("/portfolio/guidance")
def portfolio_guidance(registry=Depends(get_registry)):
    holdings = pf.parse_portfolio()
    snaps, quotes = {}, {}
    for h in holdings:
        ticker = h["ticker"]
        quote = live_quote(ticker, registry.yahoo)
        if quote:
            quotes[ticker] = quote
        daily = live_ohlcv(ticker, registry.yahoo, "1d", "1y")
        higher = live_ohlcv(ticker, registry.yahoo, "1wk", "2y")
        snap = technicals.compute_snapshot(ticker, daily, higher)
        if snap:
            snaps[ticker] = snap
    return {"guidance": signals.position_guidance(holdings, snaps, quotes)}
