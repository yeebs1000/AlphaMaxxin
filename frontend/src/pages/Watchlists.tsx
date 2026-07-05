import { useState } from "react";
import { api, useApi } from "../api";

export default function Watchlists() {
  const lists = useApi<any>("/watchlists");
  const [name, setName] = useState("");
  const [tickers, setTickers] = useState("");
  const [msg, setMsg] = useState("");

  const create = async () => {
    try {
      await api("/watchlists", {
        method: "POST",
        body: JSON.stringify({ name, tickers: tickers.split(",").map((t) => t.trim()) }),
      });
      setName(""); setTickers(""); setMsg("");
      lists.reload();
    } catch (e) { setMsg(String(e)); }
  };

  const remove = async (id: string) => {
    await api(`/watchlists/${id}`, { method: "DELETE" });
    lists.reload();
  };

  return (
    <>
      <h2>Watchlists</h2>
      <div className="panel">
        <h3>New watchlist</h3>
        <div className="row">
          <input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <input placeholder="Tickers (comma-separated)" style={{ width: 300 }}
                 value={tickers} onChange={(e) => setTickers(e.target.value)} />
          <button className="btn" onClick={create} disabled={!name.trim()}>Create</button>
          <span className="error">{msg}</span>
        </div>
      </div>
      {lists.data?.watchlists?.map((w: any) => (
        <div key={w.id} className="panel">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <h3>{w.name} <span className="muted">({w.tickers.length} tickers)</span></h3>
            <div className="row">
              <button className="btn secondary" onClick={() => remove(w.id)}>Delete</button>
            </div>
          </div>
          <div className="row">
            {w.tickers.map((t: string) => <span key={t} className="tag">{t}</span>)}
          </div>
          <p className="muted">Run a report on this list from the “Run Report” page.</p>
        </div>
      ))}
      {lists.data?.watchlists?.length === 0 && <p className="muted">No watchlists yet.</p>}
    </>
  );
}
