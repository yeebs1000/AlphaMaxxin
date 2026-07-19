import { useState } from "react";
import { api, useApi, fmtUsd, fmtPct } from "../api";

const MARKETS = ["US", "SG", "HK", "JP", "KR"] as const;

export default function Dashboard() {
  const summary = useApi<any>("/portfolio/summary");
  const guidance = useApi<any>("/portfolio/guidance");
  const status = useApi<any>("/status");
  const ledger = useApi<any>("/ledger");
  const equity = useApi<any>("/portfolio/equity");
  const scanner = useApi<any>("/scanner");
  const [markets, setMarkets] = useState<Record<string, boolean> | null>(null);
  const [savingMkts, setSavingMkts] = useState(false);

  const sc = scanner.data;
  // Local toggle state seeds from the API once, then edits optimistically.
  const mkts: Record<string, boolean> = markets ??
    Object.fromEntries(MARKETS.map((m) => [m, sc?.markets?.[m]?.enabled ?? true]));

  const toggleMarket = async (m: string) => {
    const next = { ...mkts, [m]: !mkts[m] };
    setMarkets(next);
    setSavingMkts(true);
    try {
      await api("/settings", { method: "PUT",
                               body: JSON.stringify({ scan_markets: next }) });
    } finally { setSavingMkts(false); }
  };

  const s = summary.data;
  const conv = ledger.data?.summary?.by_conviction ?? {};
  const calib = Object.entries(conv)
    .filter(([, v]: any) => v.resolved > 0 && v.hit_rate !== null)
    .map(([k, v]: any) => `${k} ${Math.round(v.hit_rate * 100)}% (${v.resolved})`);
  const openCalls = ledger.data?.summary?.open ?? 0;
  const em = equity.data?.metrics;
  const nSnaps = equity.data?.recent?.length ?? 0;
  return (
    <>
      <h2>Dashboard</h2>
      {summary.error && <div className="error">{summary.error}</div>}

      <div className="panel">
        <h3>
          <span className={`dot ${sc?.running ? "on" : ""}`} />{" "}
          24/7 Scanner
          <span className="muted" style={{ fontWeight: 400 }}>
            {" "}· {sc?.running ? "running" : "stopped"}
            {sc && !sc.local_llm && " · cloud reads capped daily"}
            {sc?.local_llm && " · local LLM (free)"}
          </span>
        </h3>
        <div className="row">
          {MARKETS.map((m) => (
            <button key={m} disabled={savingMkts}
              className={`tag mkt ${mkts[m] ? "buy" : "off"}`}
              aria-label={`${m} scanning ${mkts[m] ? "on" : "off"}`}
              aria-pressed={mkts[m]}
              title={sc?.markets?.[m]?.open ? "session open now" : "session closed"}
              onClick={() => toggleMarket(m)}>
              {mkts[m] ? "●" : "○"} {m}
              {sc?.markets?.[m]?.open && <span className="muted">live</span>}
            </button>
          ))}
        </div>
        {sc?.latest?.length ? (
          <table>
            <thead><tr><th>When</th><th>Mkt</th><th>Ticker</th><th>Setup</th><th>Score</th><th>Read</th></tr></thead>
            <tbody>
              {sc.latest.slice(0, 8).map((a: any, i: number) => (
                <tr key={i}>
                  <td className="muted">{a.at?.slice(5, 16).replace("T", " ")}</td>
                  <td>{a.region}</td>
                  <td><strong>{a.chokepoint ? "🎯 " : ""}{a.ticker}</strong></td>
                  <td><span className="tag">{a.setup}</span></td>
                  <td>{a.score ?? "—"}</td>
                  <td className="muted">{a.report_id ? "saved" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            No setups yet. The scanner watches toggled markets during their
            sessions and posts high-conviction setups here and to Telegram —
            start it with <code>py -m app.scanner</code> from backend/.
          </p>
        )}
      </div>

      <div className="cards">
        <div className="card">
          <div className="label">Portfolio Value</div>
          <div className="value">{fmtUsd(s?.total_value_usd)}</div>
          <div className={`muted ${(s?.total_pl_usd ?? 0) >= 0 ? "pos" : "neg"}`}>
            {fmtUsd(s?.total_pl_usd)} total P/L
          </div>
        </div>
        <div className="card">
          <div className="label">Holdings</div>
          <div className="value">{s?.holdings_count ?? "—"}</div>
        </div>
        <div className="card">
          <div className="label">Day Change</div>
          <div className={`value ${(s?.day_change_usd ?? 0) >= 0 ? "pos" : "neg"}`}>
            {fmtUsd(s?.day_change_usd)}
          </div>
        </div>
        <div className="card">
          <div className="label">S&amp;P 500</div>
          <div className="value">{s?.benchmark?.price?.toLocaleString() ?? "—"}</div>
          <div className={`muted ${(s?.benchmark?.change_pct ?? 0) >= 0 ? "pos" : "neg"}`}>
            {fmtPct(s?.benchmark?.change_pct, 2)}
          </div>
        </div>
        <div className="card">
          <div className="label">Book TWR</div>
          <div className={`value ${(em?.twr_pct ?? 0) >= 0 ? "pos" : "neg"}`}>
            {em ? fmtPct(em.twr_pct) : "—"}
          </div>
          <div className="muted">
            {em ? `max DD ${fmtPct(em.max_drawdown_pct)} · Sharpe ${em.sharpe_ann ?? "—"}`
                : `${nSnaps}/5 snapshots — builds daily`}
          </div>
        </div>
        <div className="card">
          <div className="label">Call Calibration</div>
          <div className="value">{calib.length ? calib[0] : "—"}</div>
          <div className="muted">
            {calib.length > 1 ? calib.slice(1).join(" · ")
              : `${openCalls} open call${openCalls === 1 ? "" : "s"} tracking`}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Position Guidance <span className="muted">(mechanical, zero LLM cost)</span></h3>
        {guidance.loading && <div className="muted">Computing…</div>}
        <table>
          <thead><tr><th>Ticker</th><th>Price</th><th>P/L %</th><th>RSI</th><th>Score</th><th>Signal</th></tr></thead>
          <tbody>
            {guidance.data?.guidance?.map((g: any) => (
              <tr key={g.ticker} title={(g.reasons || []).join("; ")}>
                <td><strong>{g.ticker}</strong> <span className="muted">{g.company}</span></td>
                <td>{g.price?.toFixed(2) ?? "—"}</td>
                <td className={(g.pl_pct ?? 0) >= 0 ? "pos" : "neg"}>{fmtPct(g.pl_pct)}</td>
                <td>{g.rsi14?.toFixed(0) ?? "—"}</td>
                <td>{g.score ?? "—"}</td>
                <td><span className={`tag ${(g.label || "").split(" ").pop()}`}>{g.label}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h3>Connections</h3>
        <div className="row">
          {status.data && [
            ...Object.entries(status.data.keys.llm).map(([k, v]) =>
              [`LLM: ${k}`, v as boolean, v ? "" : "No key set in .env"]),
            ...Object.entries(status.data.feeds).map(([k, v]) =>
              [`Feed: ${k}`, v as boolean, v ? "" : "No key set in .env"]),
            ...Object.entries(status.data.brokers).map(([k, v]: [string, any]) =>
              [`Broker: ${k}`, v.connected as boolean, v.reason || ""]),
          ].map(([name, ok, reason]) => (
            <span key={String(name)} className={`tag ${ok ? "buy" : "off"}`}
                  title={reason ? String(reason) : ""}>
              {ok ? "●" : "○"} {String(name)}
            </span>
          ))}
        </div>
      </div>
    </>
  );
}
