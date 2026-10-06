export function syncPortfolio(
  brokerSources: string[],
  request: (path: string, init: RequestInit) => Promise<any>,
) {
  return request("/portfolio/sync", {
    method: "POST", body: JSON.stringify({ broker_sources: brokerSources }),
  });
}
