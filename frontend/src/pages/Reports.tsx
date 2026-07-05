import { useState } from "react";
import { api, useApi, fmtUsd } from "../api";

export default function Reports() {
  const history = useApi<any>("/reports");
  const [openId, setOpenId] = useState<string | null>(null);

  const remove = async (id: string) => {
    await api(`/reports/${id}`, { method: "DELETE" });
    if (openId === id) setOpenId(null);
    history.reload();
  };

  return (
    <>
      <h2>Report History</h2>
      {history.data?.reports?.length === 0 && <p className="muted">No reports yet — generate one from “Run Report”.</p>}
      <table>
        <thead><tr><th>Generated</th><th>Preset</th><th>Target</th><th>Recs</th><th>Cost</th><th></th></tr></thead>
        <tbody>
          {history.data?.reports?.map((r: any) => (
            <tr key={r.id}>
              <td>{(r.created_at || r.id).slice(0, 16).replace("T", " ")}</td>
              <td>{r.preset}</td>
              <td>{r.target_label}</td>
              <td>{r.recommendations}</td>
              <td>{fmtUsd(r.cost_usd)}</td>
              <td className="row">
                <button className="btn secondary" onClick={() => setOpenId(r.id)}>View</button>
                <a className="btn secondary" href={`/api/reports/${r.id}/html`}
                   target="_blank" rel="noreferrer">↗</a>
                <button className="btn secondary" onClick={() => remove(r.id)}>✕</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {openId && <iframe className="report" src={`/api/reports/${openId}/html`} title="report" />}
    </>
  );
}
