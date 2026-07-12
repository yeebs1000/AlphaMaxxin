"""Digital footprint — developer mindshare per ticker from GitHub / npm /
PyPI / Docker Hub. Only meaningful for companies with a real open-source
surface, so coverage is a curated map (like the supply-chain chains): absent
tickers are honestly "not covered", never guessed.
# ponytail: map curated by hand, revisit quarterly; growth needs two periods,
# so stars/pulls (cumulative) are reported as levels only.
"""
from ..data import devdata
from ..data.base import OfflineError


def _safe(fn, arg):
    """Provider call that degrades to None under the offline tripwire —
    an optional lens's missing data, same contract as order_book."""
    try:
        return fn(arg)
    except OfflineError:
        return None

FOOTPRINTS = {
    "MSFT": {"github": ["microsoft/vscode", "microsoft/TypeScript"],
             "npm": ["typescript"], "pypi": [], "docker": []},
    "META": {"github": ["facebook/react", "pytorch/pytorch"],
             "npm": ["react"], "pypi": ["torch"], "docker": []},
    "GOOGL": {"github": ["kubernetes/kubernetes", "golang/go"],
              "npm": ["@angular/core"], "pypi": ["tensorflow"], "docker": []},
    "AMZN": {"github": ["aws/aws-cli", "aws/aws-cdk"],
             "npm": ["aws-cdk"], "pypi": ["boto3"], "docker": []},
    "NVDA": {"github": ["NVIDIA/TensorRT", "NVIDIA/cutlass"],
             "npm": [], "pypi": [], "docker": []},
    "ORCL": {"github": ["oracle/graal"], "npm": [], "pypi": ["oracledb"],
             "docker": []},
    "MDB": {"github": ["mongodb/mongo"], "npm": ["mongodb"],
            "pypi": ["pymongo"], "docker": ["library/mongo"]},
    "NET": {"github": ["cloudflare/workerd"], "npm": ["wrangler"],
            "pypi": [], "docker": []},
}


def collect(tickers: list[str], sources: dict | None = None) -> dict:
    """{by_ticker: {ticker: {github, npm, pypi, docker}}, not_covered: [...]}
    — per-source dicts from the devdata providers; failed sources are None."""
    sources = sources or FOOTPRINTS
    by_ticker, not_covered = {}, []
    for t in tickers:
        spec = sources.get(t)
        if not spec:
            not_covered.append(t)
            continue
        entry = {
            "github": {r: _safe(devdata.github_repo, r) for r in spec.get("github", [])},
            "npm": {p: _safe(devdata.npm_downloads, p) for p in spec.get("npm", [])},
            "pypi": {p: _safe(devdata.pypi_downloads, p) for p in spec.get("pypi", [])},
            "docker": {p: _safe(devdata.docker_pulls, p) for p in spec.get("docker", [])},
        }
        if any(v for section in entry.values() for v in section.values()):
            by_ticker[t] = entry
        else:
            not_covered.append(t)
    return {"by_ticker": by_ticker, "not_covered": not_covered}
