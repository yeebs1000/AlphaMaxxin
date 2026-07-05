import { useState } from "react";
import { api, useApi } from "../api";

type Event = { stage: string; message: string; pct: number; role?: string };

export default function RunReport() {
  const presets = useApi<any>("/presets");
  const watchlists = useApi<any>("/watchlists");
  const [preset, setPreset] = useState("Lite");
  const [kind, setKind] = useState<"portfolio" | "tickers" | "watchlist">("portfolio");
  const [tickers, setTickers] = useState("");
  const [watchlistId, setWatchlistId] = useState("");
  const [events, setEvents] = useState<Event[]>([]);
  const [running, setRunning] = useState(false);
  const [reportId, setReportId] = useState<string | null>(null);
  const [error, setError] = useState("");

  const start = async () => {
    setRunning(true); setEvents([]); setReportId(null); setError("");
    try {
      const target = kind === "tickers"
        ? { kind, tickers: tickers.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean) }
        : kind === "watchlist" ? { kind, watchlist_id: watchlistId } : { kind };
      const { run_id } = await api<any>("/reports/run", {
        method: "POST", body: JSON.stringify({ preset, target }),
      });
      const source = new EventSource(`/api/reports/run/${run_id}/events`);
      source.onmessage = (msg) => {
        const data = JSON.parse(msg.data);
        if (data.stage) setEvents((prev) => [...prev, data]);
        if (data.status === "done" && data.report_id) {
          setReportId(data.report_id); setRunning(false); source.close();
        } else if (data.status === "error") {
          setError(data.error || data.message || "run failed");
          setRunning(false); source.close();
        }
      };
      source.onerror = () => { source.close(); setRunning(false); };
    } catch (e) { setError(String(e)); setRunning(false); }
  };

  const last = events[events.length - 1];
  const selectedConfig = presets.data?.presets?.find((p: any) => p.name === preset);
  // Only the lenses THIS preset actually invokes — the full registry also
  // has 4 always-off "disabled lens" slots (no data feed yet) that aren't
  // relevant to any preset's chip row.
  const lenses = (presets.data?.lenses ?? []).filter(
    (l: any) => selectedConfig?.analysts?.includes(l.id));

  return (
    <>
      <h2>Run Report</h2>
      <div className="cards">
        {presets.data?.presets?.map((p: any) => (
          <div key={p.name} className={`card preset ${p.name === preset ? "selected" : ""}`}
               onClick={() => setPreset(p.name)}>
            <div className="value" style={{ fontSize: "1rem" }}>{p.name}</div>
            <div className="muted">{p.description}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <h3>Target</h3>
        <div className="row">
          <select value={kind} onChange={(e) => setKind(e.target.value as any)}>
            <option value="portfolio">My portfolio</option>
            <option value="tickers">Specific tickers</option>
            <option value="watchlist">Watchlist</option>
          </select>
          {kind === "tickers" &&
            <input placeholder="e.g. MSFT, NVDA" style={{ width: 260 }}
                   value={tickers} onChange={(e) => setTickers(e.target.value)} />}
          {kind === "watchlist" &&
            <select value={watchlistId} onChange={(e) => setWatchlistId(e.target.value)}>
              <option value="">Select…</option>
              {watchlists.data?.watchlists?.map((w: any) =>
                <option key={w.id} value={w.id}>{w.name}</option>)}
            </select>}
          <button className="btn" onClick={start} disabled={running}>
            {running ? "Running…" : "▶ Run"}
          </button>
        </div>
        <div className="row">
          <span className="muted">Lenses for this preset:</span>
          {lenses.map((l: any) => (
            <span key={l.id} className={`tag ${l.enabled ? "buy" : "off"}`}
                  title={l.enabled ? "" : `Disabled — ${l.enable_hint || "feed not connected"}`}>
              {l.enabled ? "●" : "○"} {l.name}
            </span>
          ))}
          <span className="tag" title="Merges the lenses above into the final report — configure its model in Settings under 'Synthesis (report writer)'.">
            → Synthesis (final report)
          </span>
        </div>
      </div>

      {(running || events.length > 0) && (
        <div className="panel">
          <h3>Progress</h3>
          <div className="progress-bar"><div style={{ width: `${last?.pct ?? 0}%` }} /></div>
          {!error && <p className="muted">{last?.message}</p>}
          {error && <div className="error">{error}</div>}
          {reportId && (
            <a className="btn" href={`/api/reports/${reportId}/html`} target="_blank"
               rel="noreferrer">Open report</a>
          )}
        </div>
      )}
    </>
  );
}
