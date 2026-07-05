import { useMemo, useState } from "react";
import { useApi } from "../api";

export default function News() {
  const portfolio = useApi<any>("/portfolio");
  const [filter, setFilter] = useState("");

  const tickers = useMemo(
    () => (portfolio.data?.holdings ?? []).map((h: any) => h.ticker),
    [portfolio.data]);
  const query = filter || tickers.join(",");
  // 5-minute auto-refresh, same cadence as the v1 news tab.
  const news = useApi<any>(query ? `/news?tickers=${encodeURIComponent(query)}` : "/portfolio", 300_000);

  return (
    <>
      <h2>News Feed</h2>
      <div className="row">
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All holdings</option>
          {tickers.map((t: string) => <option key={t} value={t}>{t}</option>)}
        </select>
        <button className="btn secondary" onClick={news.reload}>Refresh</button>
        {news.loading && <span className="muted">Loading…</span>}
      </div>
      {news.error && <div className="error">{news.error}</div>}
      {query && news.data?.items?.length === 0 &&
        <p className="muted">No articles — check Finnhub/Alpha Vantage keys in Settings.</p>}
      {query && news.data?.items?.map((a: any, i: number) => (
        <div key={i} className={`news-card ${a.sentiment}`}>
          <div>
            <span className="tag">{a.ticker}</span>{" "}
            <a href={a.url} target="_blank" rel="noreferrer"
               style={{ color: "var(--text)" }}><strong>{a.headline}</strong></a>
          </div>
          <div className="muted">
            {a.source} · {a.age} · <span className={`tag ${a.sentiment}`}>{a.sentiment}
            {a.sentiment_score ? ` ${a.sentiment_score > 0 ? "+" : ""}${a.sentiment_score.toFixed(2)}` : ""}</span>
          </div>
          {a.summary && <div className="muted">{a.summary}</div>}
        </div>
      ))}
    </>
  );
}
