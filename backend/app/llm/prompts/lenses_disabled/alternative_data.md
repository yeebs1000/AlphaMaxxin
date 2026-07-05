# Alternative Data Analyst — DISABLED LENS

Status: disabled until a real alternative-data feed is wired into
`app/data/` and registered in `ProviderRegistry.feed_status()` as `altdata`.
In v1 this agent produced LLM-only guesswork (satellite imagery, AIS
shipping, foot traffic, job postings) with a disclaimer; v2 keeps the lens
registered but off — unverifiable output cannot raise report conviction.

To enable (contribution welcome): wire a provider such as SimilarWeb (web
traffic), MarineTraffic (AIS), or a job-postings API; expose a compact
per-ticker JSON; flip `altdata` on in feed_status. Then flesh out this
prompt following the pattern of the active analyst prompts (hard
data-grounding rules + JSON output schema with stance/confidence/
key_findings/narrative_md).

## Duties once enabled
Interpret supplied alt-data series (traffic trends, shipping congestion,
hiring velocity) for the run's target tickers; flag inflections that lead
reported financials; never extrapolate beyond the supplied series.
