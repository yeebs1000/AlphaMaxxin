import type { UTCTimestamp } from "lightweight-charts";

export type PriceHistory = {
  timestamps: number[]; opens?: number[]; closes: number[];
  highs: number[]; lows: number[];
};

export function toCandles(d: PriceHistory) {
  if (!Array.isArray(d.opens))
    throw new Error("Observed opening prices are unavailable. Refresh the history cache before charting.");
  const columns = [d.timestamps, d.opens, d.closes, d.highs, d.lows];
  if (!columns.every((col) => Array.isArray(col) && col.length === d.timestamps.length)
      || d.timestamps.length === 0)
    throw new Error("Price history is empty or its OHLC columns do not match.");
  return d.timestamps.map((t, i) => ({
    time: t as UTCTimestamp, open: d.opens![i],
    high: d.highs[i], low: d.lows[i], close: d.closes[i],
  })).map((bar, i) => {
    const prices = [bar.open, bar.high, bar.low, bar.close];
    if (!Number.isSafeInteger(bar.time) || bar.time <= 0
        || (i > 0 && bar.time <= d.timestamps[i - 1])
        || !prices.every((price) => Number.isFinite(price) && price > 0)
        || bar.low > Math.min(bar.open, bar.close)
        || bar.high < Math.max(bar.open, bar.close))
      throw new Error(`Invalid OHLC observation at row ${i + 1}.`);
    return bar;
  });
}
