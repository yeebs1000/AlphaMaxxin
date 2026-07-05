"""Charts, news, and ticker search."""
from fastapi import APIRouter, Depends, HTTPException

from ..skills import news as news_skill
from .deps import get_registry

router = APIRouter(tags=["market"])

_VALID_RANGES = {"1mo", "3mo", "6mo", "ytd", "1y", "2y", "5y"}


@router.get("/charts/history")
def chart_history(ticker: str, range: str = "1y", interval: str = "1d",
                  registry=Depends(get_registry)):
    if range not in _VALID_RANGES:
        raise HTTPException(400, f"range must be one of {sorted(_VALID_RANGES)}")
    symbol, name = registry.yahoo.resolve_symbol(ticker)
    if not symbol:
        raise HTTPException(404, f"could not resolve '{ticker}'")
    bars = registry.yahoo.ohlcv(symbol, interval, range)
    if not bars:
        raise HTTPException(404, f"no data for '{ticker}'")
    return {"ticker": ticker, "symbol": symbol, "name": name, **bars}


@router.get("/news")
def get_news(tickers: str, limit: int = 20, registry=Depends(get_registry)):
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        raise HTTPException(400, "tickers query param required (comma-separated)")
    articles = news_skill.fetch_and_merge(registry, ticker_list)
    return news_skill.digest(articles, max_items=limit)


@router.get("/search")
def search(q: str, registry=Depends(get_registry)):
    return {"results": registry.yahoo.search(q)}
