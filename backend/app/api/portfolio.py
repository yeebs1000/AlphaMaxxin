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


class ExternalHolding(Holding):
    broker: str = "External"


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


@router.get("/portfolio/external")
def get_external():
    """External holdings (IPO/CDP allotments, placements, other brokers) as a
    list of rows for the editor."""
    data = pf.load_external_holdings()
    return {"holdings": [{"ticker": t, **v} for t, v in data.items()]}


@router.put("/portfolio/external")
def put_external(holdings: list[ExternalHolding]):
    """Replace the external-holdings file. Keyed by ticker (a duplicate
    ticker's last row wins); merged into the book on the next broker sync."""
    data = {h.ticker.strip().upper(): {k: v for k, v in h.model_dump().items()
                                       if k != "ticker"}
            for h in holdings if h.ticker.strip()}
    pf.save_external_holdings(data)
    return {"holdings": [{"ticker": t, **v} for t, v in data.items()]}


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
