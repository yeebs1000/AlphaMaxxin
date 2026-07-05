# Global Order Book & Liquidity Profiler — DISABLED LENS

Status: disabled until a level-2 depth feed is wired into `app/data/` and
registered in `ProviderRegistry.feed_status()` as `orderbook`. In v1 this
agent narrated bid/ask depth, order-flow toxicity, and dealer gamma from
LLM imagination; v2 keeps the lens registered but off. (Basic volume-profile
levels — POC/value area — are already covered by the Technicals analyst
from real bars.)

To enable (contribution welcome): the moomoo OpenD order-book subscription
(`get_moomoo_orderbook` already exists in `app/brokers/moomoo_client.py`)
is the natural first feed — expose a per-ticker depth snapshot provider,
flip `orderbook` on in feed_status, and flesh out this prompt following the
active-analyst pattern.

## Duties once enabled
Read supplied depth snapshots for spread, depth imbalance, and notable
resting size around the Technicals analyst's levels; comment on execution
feasibility for the Risk analyst's sizing.
