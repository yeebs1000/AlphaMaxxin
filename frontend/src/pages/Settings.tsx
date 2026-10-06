import { useEffect, useState } from "react";
import { api, useApi, fmtUsd } from "../api";

const MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash",
                "claude-sonnet-4-6", "claude-opus-4-8",
                "gpt-4o-mini", "local/qwen3:14b"];
const MARKETS = ["US", "SG", "HK", "JP", "KR"] as const;
const ROLE_LABELS: Record<string, string> = {
  macro: "Macro Analyst", fundamentals: "Fundamentals Analyst",
  technicals_options: "Technicals & Options Analyst",
  news_catalysts: "News & Catalysts Analyst", risk: "Risk Analyst",
  order_book: "Order Book & Liquidity Profiler",
  ml_alpha: "Machine Learning Alpha Extractor",
  alternative_data: "Alternative Data Analyst",
  digital_footprint: "Digital Footprint & Developer Momentum Scanner",
  synthesis: "Synthesis (report writer)",
};

export default function Settings() {
  const settings = useApi<any>("/settings");
  const costs = useApi<any>("/costs");
  const [models, setModels] = useState<Record<string, string>>({});
  const [cacheOn, setCacheOn] = useState(true);
  const [markets, setMarkets] = useState<Record<string, boolean>>({});
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings.data) {
      setModels(settings.data.models);
      setCacheOn(settings.data.llm_cache_enabled);
      setMarkets(settings.data.scan_markets ?? {});
    }
  }, [settings.data]);

  const save = async () => {
    setBusy(true);
    try {
      await api("/settings", { method: "PUT",
        body: JSON.stringify({ models, llm_cache_enabled: cacheOn, scan_markets: markets }) });
      setMsg("Saved.");
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  };

  const toggleMarket = (m: string) => setMarkets({ ...markets, [m]: !markets[m] });

  return (
    <>
      <h2>Settings</h2>
      <div className="panel">
        <h3>Model per role</h3>
        <p className="muted">Enter a model ID available to your configured provider: Gemini, Claude,
          OpenAI (for example <code>gpt-4o-mini</code>), or <code>local/your-model-id</code>.
          Local models require <code>LOCAL_LLM_BASE_URL</code> in <code>.env</code>.
          Suggestions are examples; availability and prices depend on your provider.</p>
        <datalist id="model-suggestions">
          {MODELS.map((m) => <option key={m} value={m} />)}
        </datalist>
        {Object.entries(ROLE_LABELS).map(([role, label]) => (
          <div key={role} className="row">
            <label htmlFor={`model-${role}`} style={{ width: 240 }}>{label}</label>
            <input id={`model-${role}`} name={`model.${role}`} type="text" list="model-suggestions"
                   value={models[role] ?? ""} disabled={busy || settings.loading}
                   onChange={(e) => setModels({ ...models, [role]: e.target.value })} />
          </div>
        ))}
        <div className="row">
          <label><input type="checkbox" checked={cacheOn} disabled={busy || settings.loading}
                        onChange={(e) => setCacheOn(e.target.checked)} /> LLM response cache
            <span className="muted"> (matching cached responses within 24h avoid another model call)</span></label>
        </div>
        <div className="row">
          <button className="btn" onClick={save} disabled={busy || settings.loading || !!settings.error}>Save</button>
          <span className="muted">{settings.error ?? msg}</span>
        </div>
      </div>

      <div className="panel">
        <h3>Market scan scope</h3>
        <p className="muted">Broad-scan presets (Opportunist, Macro Pulse, region runs) only
          screen toggled-on markets.</p>
        <div className="row">
          {MARKETS.map((m) => (
            <button key={m} className={`tag mkt ${markets[m] ?? true ? "buy" : "off"}`}
                    aria-pressed={markets[m] ?? true}
                    disabled={busy || settings.loading}
                    onClick={() => toggleMarket(m)}>
              {(markets[m] ?? true) ? "●" : "○"} {m}
            </button>
          ))}
        </div>
        <div className="row">
          <button className="btn" onClick={save} disabled={busy || settings.loading || !!settings.error}>Save</button>
          <span className="muted">{msg}</span>
        </div>
      </div>

      <div className="panel">
        <h3>LLM spend</h3>
        {costs.data && (
          <div className="cards">
            <div className="card"><div className="label">Total spend</div>
              <div className="value">{fmtUsd(costs.data.usd)}</div></div>
            <div className="card"><div className="label">Calls</div>
              <div className="value">{costs.data.calls}</div>
              <div className="muted">{costs.data.cached_calls} served from cache</div></div>
            <div className="card"><div className="label">Tokens</div>
              <div className="value">{((costs.data.in_tokens + costs.data.out_tokens) / 1000).toFixed(1)}k</div></div>
          </div>
        )}
      </div>

      <div className="panel">
        <h3>API keys</h3>
        <p className="muted">Keys are stored in the project’s <code>.env</code> file and sent to the
          corresponding provider to authenticate requests. Cloud report generation sends portfolio
          and research context to the selected model provider. A local model uses your configured endpoint.
          Re-run the setup wizard (<code>start.bat</code> / <code>start.sh</code>) to add or change keys,
          then restart the backend.</p>
      </div>
    </>
  );
}
