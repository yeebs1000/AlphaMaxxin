import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import ts from "typescript";
import { toCandles } from "../src/chartData.ts";
import { syncPortfolio } from "../src/portfolioSync.ts";
import { api } from "../src/api.ts";

// Exercise the real TSX page without a browser or another test framework.
async function loadPage(path) {
  const url = new URL(path, import.meta.url);
  const source = await readFile(url, "utf8");
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX },
  });
  const code = outputText.replace(/from ["']([^"']+)["']/g, (_, name) => {
    const resolved = name.startsWith(".")
      ? new URL(name.endsWith(".ts") ? name : `${name}.ts`, url).href
      : import.meta.resolve(name);
    return `from ${JSON.stringify(resolved)}`;
  });
  return import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);
}

const history = {
  timestamps: [100, 200], opens: [95, 120], closes: [100, 122],
  highs: [105, 125], lows: [90, 115], volumes: [10, 20],
};

test("candles retain the actual first open and overnight gap", () => {
  assert.deepEqual(toCandles(history), [
    { time: 100, open: 95, high: 105, low: 90, close: 100 },
    { time: 200, open: 120, high: 125, low: 115, close: 122 },
  ]);
});

test("history without observed opens is unavailable, not fabricated", () => {
  const { opens, ...cached } = history;
  assert.throws(() => toCandles(cached), /open/i);
});

test("nonfinite, mismatched, unordered and incoherent candles are rejected", () => {
  for (const change of [
    { opens: [95, NaN] }, { closes: [100, Infinity] }, { lows: [90, 123] },
    { highs: [105, 119] }, { opens: [95] }, { timestamps: [200, 100] },
    { timestamps: [100, 100] }, { closes: [100, -1] },
  ]) assert.throws(() => toCandles({ ...history, ...change }));
});

test("broker sync sends precisely the selected sources, including external-only", async () => {
  const original = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, init) => {
    requests.push({ url, method: init.method, body: JSON.parse(init.body ?? "null") });
    return new Response(JSON.stringify({ success: true, holdings: [] }));
  };
  try {
    await syncPortfolio(["tiger"], api);
    await syncPortfolio([], api);
    assert.deepEqual(requests, [
      { url: "/api/portfolio/sync", method: "POST", body: { broker_sources: ["tiger"] } },
      { url: "/api/portfolio/sync", method: "POST", body: { broker_sources: [] } },
    ]);
  } finally { globalThis.fetch = original; }
});

test("Settings renders model controls for all nine analysts and synthesis", async () => {
  const { default: Settings } = await loadPage("../src/pages/Settings.tsx");
  const html = renderToStaticMarkup(createElement(Settings));
  for (const label of ["Macro Analyst", "Fundamentals Analyst", "Technicals &amp; Options Analyst",
    "News &amp; Catalysts Analyst", "Risk Analyst", "Order Book &amp; Liquidity Profiler",
    "Machine Learning Alpha Extractor", "Alternative Data Analyst",
    "Digital Footprint &amp; Developer Momentum Scanner", "Synthesis (report writer)"])
    assert.ok(html.includes(label), `missing model control: ${label}`);
  assert.equal((html.match(/name="model\./g) ?? []).length, 10);
  assert.ok(html.includes('type="text"'), "custom provider IDs must be editable");
  assert.ok(!html.includes("<select"), "model IDs must not be restricted to a preset list");
});

test("Portfolio requires an intentional source choice before replacement", async () => {
  const { default: Portfolio } = await loadPage("../src/pages/Portfolio.tsx");
  const html = renderToStaticMarkup(createElement(Portfolio));
  assert.match(html, /<button[^>]*disabled=""[^>]*>[^<]*Sync/);
  assert.ok(html.includes("External holdings only"));
});
