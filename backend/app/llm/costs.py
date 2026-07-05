"""Token/cost meter — records every LLM call per run and cumulatively.
Prices are USD per 1M tokens (input, output); unknown models cost 0 and are
flagged so the UI shows "unpriced" rather than a false $0 saving."""
import datetime
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
COSTS_FILE = str(REPO_ROOT / "data_store" / "costs.json")

PRICE_TABLE = {  # USD per 1M tokens: (input, output)
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-3-flash-preview": (0.20, 0.80),
    "gemini-3.5-flash": (0.25, 1.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
    "gpt-4o-mini": (0.15, 0.60),
}


def price_call(model: str, in_tokens: int, out_tokens: int) -> dict:
    prices = PRICE_TABLE.get(model)
    usd = ((in_tokens * prices[0] + out_tokens * prices[1]) / 1_000_000
           if prices else 0.0)
    return {"model": model, "in_tokens": in_tokens, "out_tokens": out_tokens,
            "usd": round(usd, 6), "priced": prices is not None}


class CostMeter:
    def __init__(self, file_path: str | None = None):
        self.file_path = file_path or COSTS_FILE
        self._runs: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self._runs, f, indent=1)

    def record(self, run_id: str, role: str, model: str,
               in_tokens: int, out_tokens: int, cached: bool = False) -> dict:
        entry = price_call(model, in_tokens, out_tokens)
        entry.update({
            "run_id": run_id, "role": role, "cached": cached,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        if cached:
            entry["usd"] = 0.0  # served from cache — nothing billed
        self._runs.append(entry)
        self._save()
        return entry

    def run_total(self, run_id: str) -> dict:
        calls = [c for c in self._runs if c["run_id"] == run_id]
        return self._totalize(calls)

    def totals(self) -> dict:
        return self._totalize(self._runs)

    @staticmethod
    def _totalize(calls: list[dict]) -> dict:
        return {
            "calls": len(calls),
            "cached_calls": sum(1 for c in calls if c.get("cached")),
            "in_tokens": sum(c["in_tokens"] for c in calls),
            "out_tokens": sum(c["out_tokens"] for c in calls),
            "usd": round(sum(c["usd"] for c in calls), 4),
        }
