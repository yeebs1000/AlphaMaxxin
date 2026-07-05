// ponytail: fetch + one hook instead of a query library — add TanStack Query
// only if caching/invalidation ever gets hairy.
import { useCallback, useEffect, useState } from "react";

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.status === 204 ? (undefined as T) : res.json();
}

export function useApi<T = any>(path: string, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    setLoading(true);
    api<T>(path)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, [path]);

  useEffect(() => {
    reload();
    if (refreshMs) {
      const id = setInterval(reload, refreshMs);
      return () => clearInterval(id);
    }
  }, [reload, refreshMs]);

  return { data, error, loading, reload };
}

export const fmtUsd = (v?: number | null) =>
  v == null ? "—" : v.toLocaleString("en-US", { style: "currency", currency: "USD" });
export const fmtPct = (v?: number | null, digits = 1) =>
  v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
