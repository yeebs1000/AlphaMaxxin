import { useEffect, useRef, useState } from "react";
import { createChart, IChartApi } from "lightweight-charts";
import { api, fmtPct } from "../api";
import { toCandles } from "../chartData";

const RANGES = ["1mo", "3mo", "6mo", "ytd", "1y", "5y"];

export default function Charts() {
  const [ticker, setTicker] = useState("MSFT");
  const [input, setInput] = useState("MSFT");
  const [range, setRange] = useState("1y");
  const [info, setInfo] = useState<{ name?: string; ret?: number; err?: string }>({});
  const div = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!div.current) return;
    chart.current = createChart(div.current, {
      height: 460,
      layout: { background: { color: "#16213e" }, textColor: "#9aa0b5" },
      grid: { vertLines: { color: "#2a3557" }, horzLines: { color: "#2a3557" } },
      crosshair: { mode: 0 },
    });
    const series = chart.current.addCandlestickSeries({
      upColor: "#2ecc71", downColor: "#e74c3c",
      wickUpColor: "#2ecc71", wickDownColor: "#e74c3c", borderVisible: false,
    });
    (chart.current as any)._series = series;
    const resize = () => chart.current?.applyOptions({ width: div.current!.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); chart.current?.remove(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    (chart.current as any)?._series?.setData([]);
    setInfo({});
    api<any>(`/charts/history?ticker=${encodeURIComponent(ticker)}&range=${range}`,
             { signal: controller.signal })
      .then((d) => {
        const series = (chart.current as any)?._series;
        if (!series || controller.signal.aborted) return;
        const bars = toCandles(d);
        series.setData(bars);
        chart.current?.timeScale().fitContent();
        const first = d.closes[0], last = d.closes[d.closes.length - 1];
        setInfo({ name: d.name, ret: first ? ((last - first) / first) * 100 : 0 });
      })
      .catch((e) => { if (!controller.signal.aborted) setInfo({ err: String(e) }); });
    return () => controller.abort();
  }, [ticker, range]);

  return (
    <>
      <h2>Historical Chart</h2>
      <div className="row">
        <input value={input} onChange={(e) => setInput(e.target.value.toUpperCase())}
               onKeyDown={(e) => e.key === "Enter" && setTicker(input)}
               placeholder="Ticker" style={{ width: 130 }} />
        <button className="btn" onClick={() => setTicker(input)}>Load</button>
        {RANGES.map((r) => (
          <button key={r} className={`btn ${r === range ? "" : "secondary"}`}
                  onClick={() => setRange(r)}>{r.toUpperCase()}</button>
        ))}
        <span className="muted">
          {info.err ? info.err : info.name ? <>{info.name} · <span
            className={(info.ret ?? 0) >= 0 ? "pos" : "neg"}>{fmtPct(info.ret)}</span></> : ""}
        </span>
      </div>
      <div ref={div} />
    </>
  );
}
