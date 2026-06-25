import sys, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Windows consoles default to cp1252, which can't encode the emoji/arrows
# format_news_for_llm() embeds in its output — reconfigure to UTF-8 so this
# script doesn't crash on a vanilla terminal.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Load .env from the repo root
with open(os.path.join(ROOT, '.env')) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip()

from news_fetcher import fetch_finnhub_news, fetch_alphavantage_news, fetch_portfolio_news, format_news_for_llm

print("=== Finnhub: MSFT (7 days) ===")
arts = fetch_finnhub_news("MSFT", days=7)
print("  Articles fetched:", len(arts))
if arts:
    print("  First:", arts[0]["title"][:80])
    print("  Time: ", arts[0]["published_rel"])

print()
print("=== Alpha Vantage: MSFT ===")
av_arts = fetch_alphavantage_news("MSFT")
print("  Articles fetched:", len(av_arts))
if av_arts:
    print("  First:", av_arts[0]["title"][:80])
    print("  Sentiment:", av_arts[0]["sentiment"], av_arts[0]["sentiment_score"])

print()
print("=== Portfolio news (MSFT, GRAB) ===")
combined = fetch_portfolio_news(["MSFT", "GRAB"], max_per_ticker=3)
print("  Total deduplicated articles:", len(combined))

print()
print("=== LLM format preview ===")
digest = format_news_for_llm(combined, max_articles=6)
print(digest[:1500])
