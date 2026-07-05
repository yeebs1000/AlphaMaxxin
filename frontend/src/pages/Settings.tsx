import { useEffect, useState } from "react";
import { api, useApi, fmtUsd } from "../api";

const MODELS = ["gemini-2.5-flash", "gemini-3-flash-preview", "gemini-3.5-flash",
                "claude-3-5-sonnet-latest", "claude-sonnet-4-6", "claude-opus-4-8"];
const ROLE_LABELS: Record<string, string> = {
  macro: "Macro Analyst", fundamentals: "Fundamentals Analyst",
  technicals_options: "Technicals & Options Analyst",
  news_catalysts: "News & Catalysts Analyst", risk: "Risk Analyst",
  synthesis: "Synthesis (report writer)",
};

export default function Settings() {
  const settings = useApi<any>("/settings");
  const costs = useApi<any>("/costs");
  const [models, setModels] = useState<Record<string, string>>({});
  const [cacheOn, setCacheOn] = useState(true);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (settings.data) {
      setModels(settings.data.models);
      setCacheOn(settings.data.llm_cache_enabled);
    }
  }, [settings.data]);

  const save = async () => {
    await api("/settings", { method: "PUT",
      body: JSON.stringify({ models, llm_cache_enabled: cacheOn }) });
    setMsg("Saved.");
  };

  return (
    <>
      <h2>Settings</h2>
      <div className="panel">
        <h3>Model per role</h3>
        <p className="muted">Cheap tier for analysts, better tier for the synthesis call is the cost-effective default.</p>
        {Object.entries(ROLE_LABELS).map(([role, label]) => (
          <div key={role} className="row">
            <span style={{ width: 240 }}>{label}</span>
            <select value={models[role] ?? ""} onChange={(e) =>
              setModels({ ...models, [role]: e.target.value })}>
              {MODELS.map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
        ))}
        <div className="row">
          <label><input type="checkbox" checked={cacheOn}
                        onChange={(e) => setCacheOn(e.target.checked)} /> LLM response cache
            <span className="muted"> (identical re-runs within 24h are free)</span></label>
        </div>
        <div className="row">
          <button className="btn" onClick={save}>Save</button>
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
        <p className="muted">Keys live in the project’s <code>.env</code> file and never leave this machine.
          Re-run the setup wizard (<code>start.bat</code> / <code>start.sh</code>) to add or change keys,
          then restart the backend.</p>
      </div>
    </>
  );
}
