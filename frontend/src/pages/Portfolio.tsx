import { useEffect, useState } from "react";
import { api } from "../api";
import { syncPortfolio } from "../portfolioSync";

type Holding = { company: string; ticker: string; quantity: number;
                 cost_price: number; currency: string };
type ExternalHolding = Holding & { broker: string };

const CURRENCIES = ["USD", "SGD", "HKD", "JPY", "CNY", "MYR"];
const BROKERS = ["moomoo", "ibkr", "tiger"];

export default function Portfolio() {
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [external, setExternal] = useState<ExternalHolding[]>([]);
  const [msg, setMsg] = useState("");
  const [extMsg, setExtMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [brokerSources, setBrokerSources] = useState<string[]>([]);
  const [externalOnly, setExternalOnly] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const locked = busy || !loaded;

  const load = () => api<any>("/portfolio").then((d) => setHoldings(d.holdings));
  const loadExternal = () =>
    api<any>("/portfolio/external").then((d) => setExternal(d.holdings));
  useEffect(() => {
    Promise.all([load(), loadExternal()]).then(() => setLoaded(true))
      .catch((e) => setMsg(String(e)));
  }, []);

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
    if (!brokerSources.length && !externalOnly) return;
    setBusy(true);
    setMsg("Syncing from brokers…");
    try {
      const r = await syncPortfolio(brokerSources, api);
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
      <div className="panel">
        <h3>Broker sources for replacement</h3>
        <p className="muted">Sync replaces the saved book with all selected brokers plus saved
          external holdings. Select every broker you intend to include; unselected brokers are
          excluded. If any selected broker fails, the saved book stays unchanged.
          Choose external-only explicitly to replace the book using saved external holdings;
          an empty external list clears the book.</p>
        <div className="row">
          {BROKERS.map((broker) => <label key={broker}>
            <input type="checkbox" checked={brokerSources.includes(broker)} disabled={locked}
                   onChange={(e) => {
                     setExternalOnly(false);
                     setBrokerSources(e.target.checked
                       ? [...brokerSources, broker] : brokerSources.filter((b) => b !== broker));
                   }} />
            {broker === "ibkr" ? "IBKR" : broker === "tiger" ? "Tiger" : "Moomoo"}
          </label>)}
          <label><input type="checkbox" checked={externalOnly} disabled={locked}
                        onChange={(e) => {
                          setExternalOnly(e.target.checked);
                          setBrokerSources([]);
                        }} /> External holdings only</label>
        </div>
      </div>
      <div className="row">
        <button className="btn" onClick={sync} disabled={locked || (!brokerSources.length && !externalOnly)}>
          {externalOnly ? "⇄ Sync External Only" : "⇄ Sync Selected Brokers"}</button>
        <button className="btn secondary" disabled={locked} onClick={() =>
          setHoldings([...holdings, { company: "", ticker: "", quantity: 0,
                                      cost_price: 0, currency: "USD" }])}>+ Add Row</button>
        <button className="btn" onClick={save} disabled={locked}>Save</button>
        <span className="muted">{msg}</span>
      </div>
      <fieldset disabled={locked} style={{ border: 0, padding: 0 }}>
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
      </fieldset>
      <p className="muted">Edits are stored locally in Portfolio.md (gitignored).
        Report generation can send holdings and research context to the selected cloud model
        provider; data and broker requests contact their respective services.</p>

      <h2>External Holdings</h2>
      <p className="muted">
        Shares no broker API can see — IPO/CDP allotments, placements, ESPP,
        other brokers. These survive every broker sync; a ticker held in a
        broker too merges with summed quantity and weighted-average cost.
      </p>
      <div className="row">
        <button className="btn secondary" disabled={locked} onClick={() =>
          setExternal([...external, { company: "", ticker: "", quantity: 0,
                                      cost_price: 0, currency: "SGD",
                                      broker: "CDP (IPO)" }])}>+ Add Row</button>
        <button className="btn" onClick={saveExternal} disabled={locked}>Save External</button>
        <span className="muted">{extMsg}</span>
      </div>
      <fieldset disabled={locked} style={{ border: 0, padding: 0 }}>
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
      </fieldset>
    </>
  );
}
