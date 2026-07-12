import { useEffect, useState } from "react";
import { api } from "../api";

type Holding = { company: string; ticker: string; quantity: number;
                 cost_price: number; currency: string };
type ExternalHolding = Holding & { broker: string };

const CURRENCIES = ["USD", "SGD", "HKD", "JPY", "CNY", "MYR"];

export default function Portfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [external, setExternal] = useState<ExternalHolding[]>([]);
  const [msg, setMsg] = useState("");
  const [extMsg, setExtMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api<any>("/portfolio").then((d) => setHoldings(d.holdings));
  const loadExternal = () =>
    api<any>("/portfolio/external").then((d) => setExternal(d.holdings));
  useEffect(() => { load(); loadExternal(); }, []);

  const edit = (i: number, field: keyof Holding, value: string) =>
    setHoldings(holdings.map((h, j) => j === i
      ? { ...h, [field]: field === "quantity" || field === "cost_price" ? Number(value) || 0 : value }
      : h));

  const save = async () => {
    setBusy(true);
    try {
      await api("/portfolio", { method: "PUT", body: JSON.stringify(holdings) });
      await load();
      setMsg("Saved.");
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  };

  const sync = async () => {
    setBusy(true);
    setMsg("Syncing from brokers…");
    try {
      const r = await api<any>("/portfolio/sync", { method: "POST" });
      setMsg(r.success ? `Synced ${r.holdings.length} holdings.` : r.error);
      if (r.success) await load();
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  };

  const editExternal = (i: number, field: keyof ExternalHolding, value: string) =>
    setExternal(external.map((h, j) => j === i
      ? { ...h, [field]: field === "quantity" || field === "cost_price" ? Number(value) || 0 : value }
      : h));

  const saveExternal = async () => {
    setBusy(true);
    try {
      await api("/portfolio/external", { method: "PUT", body: JSON.stringify(external) });
      await loadExternal();
      setExtMsg("Saved — merged into the book on next sync.");
    } catch (e) { setExtMsg(String(e)); } finally { setBusy(false); }
  };

  return (
    <>
      <h2>Portfolio Editor</h2>
      <div className="row">
        <button className="btn" onClick={sync} disabled={busy}>⇄ Sync Brokers</button>
        <button className="btn secondary" onClick={() =>
          setHoldings([...holdings, { company: "", ticker: "", quantity: 0,
                                      cost_price: 0, currency: "USD" }])}>+ Add Row</button>
        <button className="btn" onClick={save} disabled={busy}>Save</button>
        <span className="muted">{msg}</span>
      </div>
      <table>
        <thead><tr><th>Company</th><th>Ticker</th><th>Quantity</th><th>Cost Price</th><th>Currency</th><th></th></tr></thead>
        <tbody>
          {holdings.map((h, i) => (
            <tr key={i}>
              <td><input value={h.company} onChange={(e) => edit(i, "company", e.target.value)} /></td>
              <td><input value={h.ticker} style={{ width: 90 }} onChange={(e) => edit(i, "ticker", e.target.value)} /></td>
              <td><input value={h.quantity} style={{ width: 90 }} onChange={(e) => edit(i, "quantity", e.target.value)} /></td>
              <td><input value={h.cost_price} style={{ width: 110 }} onChange={(e) => edit(i, "cost_price", e.target.value)} /></td>
              <td>
                <select value={h.currency} onChange={(e) => edit(i, "currency", e.target.value)}>
                  {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </td>
              <td><button className="btn secondary" onClick={() =>
                setHoldings(holdings.filter((_, j) => j !== i))}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">Edits write to Portfolio.md (gitignored — your real holdings never leave this machine).</p>

      <h2>External Holdings</h2>
      <p className="muted">
        Shares no broker API can see — IPO/CDP allotments, placements, ESPP,
        other brokers. These survive every broker sync; a ticker held in a
        broker too merges with summed quantity and weighted-average cost.
      </p>
      <div className="row">
        <button className="btn secondary" onClick={() =>
          setExternal([...external, { company: "", ticker: "", quantity: 0,
                                      cost_price: 0, currency: "SGD",
                                      broker: "CDP (IPO)" }])}>+ Add Row</button>
        <button className="btn" onClick={saveExternal} disabled={busy}>Save External</button>
        <span className="muted">{extMsg}</span>
      </div>
      <table>
        <thead><tr><th>Company</th><th>Ticker</th><th>Quantity</th><th>Cost Price</th><th>Currency</th><th>Source</th><th></th></tr></thead>
        <tbody>
          {external.map((h, i) => (
            <tr key={i}>
              <td><input value={h.company} onChange={(e) => editExternal(i, "company", e.target.value)} /></td>
              <td><input value={h.ticker} style={{ width: 90 }} placeholder="XYZ.SI" onChange={(e) => editExternal(i, "ticker", e.target.value)} /></td>
              <td><input value={h.quantity} style={{ width: 90 }} onChange={(e) => editExternal(i, "quantity", e.target.value)} /></td>
              <td><input value={h.cost_price} style={{ width: 110 }} onChange={(e) => editExternal(i, "cost_price", e.target.value)} /></td>
              <td>
                <select value={h.currency} onChange={(e) => editExternal(i, "currency", e.target.value)}>
                  {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
                </select>
              </td>
              <td><input value={h.broker} style={{ width: 120 }} onChange={(e) => editExternal(i, "broker", e.target.value)} /></td>
              <td><button className="btn secondary" onClick={() =>
                setExternal(external.filter((_, j) => j !== i))}>✕</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
