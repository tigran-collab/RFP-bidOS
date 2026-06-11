import { useState } from "react";

import Layout from "./components/Layout.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Opportunities from "./pages/Opportunities.jsx";
import Scraper from "./pages/Scraper.jsx";
import Settings from "./pages/Settings.jsx";

const pages = {
  dashboard: Dashboard,
  opportunities: Opportunities,
  scraper: Scraper,
  settings: Settings,
};

export default function App() {
  const [page, setPage] = useState("dashboard");
  const Page = pages[page];

  return (
    <Layout currentPage={page} onNavigate={setPage}>
      <Page />
    </Layout>
  );
}
