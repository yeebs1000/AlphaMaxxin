# Digital Footprint & Developer Momentum Scanner — DISABLED LENS

Status: disabled until developer-ecosystem stats providers are wired into
`app/data/` and registered in `ProviderRegistry.feed_status()` as `devdata`.
In v1 this agent recalled GitHub stars and package downloads from training
data; v2 keeps the lens registered but off.

To enable (contribution welcome): the GitHub REST API, PyPI download stats
(pypistats), and npm registry counts are all free and keyless or
free-tier — add providers exposing per-company {repo star velocity,
contributor trend, package download trend}, flip `devdata` on in
feed_status, and flesh out this prompt following the active-analyst pattern.

## Duties once enabled
Read supplied developer-adoption series for tech names in the run's
targets; treat adoption inflections as early, noisy leading indicators and
size the claim accordingly; never quote a star count or download figure not
present in the input.
