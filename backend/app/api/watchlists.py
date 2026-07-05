from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import watchlists as wl

router = APIRouter(tags=["watchlists"])


class WatchlistIn(BaseModel):
    name: str
    tickers: list[str] = []


@router.get("/watchlists")
def list_watchlists():
    return {"watchlists": wl.list_watchlists()}


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistIn):
    return wl.create_watchlist(body.name, body.tickers)


@router.get("/watchlists/{watchlist_id}")
def get_watchlist(watchlist_id: str):
    found = wl.get_watchlist(watchlist_id)
    if not found:
        raise HTTPException(404, "watchlist not found")
    return found


@router.put("/watchlists/{watchlist_id}")
def update_watchlist(watchlist_id: str, body: WatchlistIn):
    updated = wl.update_watchlist(watchlist_id, body.name, body.tickers)
    if not updated:
        raise HTTPException(404, "watchlist not found")
    return updated


@router.delete("/watchlists/{watchlist_id}", status_code=204)
def delete_watchlist(watchlist_id: str):
    if not wl.delete_watchlist(watchlist_id):
        raise HTTPException(404, "watchlist not found")
