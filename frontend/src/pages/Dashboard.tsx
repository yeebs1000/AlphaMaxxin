import { useApi, fmtUsd, fmtPct } from "../api";

export default function Dashboard() {
  const summary = useApi<any>("/portfolio/summary");
  const guidance = useApi<any>("/portfolio/guidance");
  const status = useApi<any>("/status");

  const s = summary.data;
  return (
    <>
      <h2>Dashboard</h2>
      {summary.error && <div className="error">{summary.error}</div>}
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
