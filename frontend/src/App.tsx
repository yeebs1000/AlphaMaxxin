import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import Charts from "./pages/Charts";
import News from "./pages/News";
import Watchlists from "./pages/Watchlists";
import RunReport from "./pages/RunReport";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";

// ponytail: tab state instead of react-router — add routing if deep links matter.
const PAGES = {
  "📊 Dashboard": Dashboard,
  "📋 Portfolio": Portfolio,
  "📈 Charts": Charts,
  "📰 News": News,
  "⭐ Watchlists": Watchlists,
  "🧠 Run Report": RunReport,
  "📄 Reports": Reports,
  "⚙️ Settings": Settings,
} as const;

export default function App() {
  const [page, setPage] = useState<keyof typeof PAGES>("📊 Dashboard");
  const Page = PAGES[page];
  return (
    <>
      <nav className="sidebar">
        <h1>Alpha<span>Maxxin</span></h1>
        {Object.keys(PAGES).map((name) => (
          <button key={name} className={name === page ? "active" : ""}
                  onClick={() => setPage(name as keyof typeof PAGES)}>
            {name}
          </button>
        ))}
      </nav>
      <main className="main"><Page /></main>
    </>
  );
}
