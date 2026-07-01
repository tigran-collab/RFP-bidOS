import { useState } from "react";

import Layout from "./components/Layout.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import LocalAIChatPage from "./pages/LocalAIChatPage.jsx";
import OpportunityDetail from "./pages/OpportunityDetail.jsx";
import Opportunities from "./pages/Opportunities.jsx";
import NewOpportunity from "./pages/NewOpportunity.jsx";
import ReviewQueue from "./pages/ReviewQueue.jsx";
import Scraper from "./pages/Scraper.jsx";
import Portals from "./pages/Portals.jsx";
import Settings from "./pages/Settings.jsx";

const pages = {
  dashboard: Dashboard,
  opportunities: Opportunities,
  newOpportunity: NewOpportunity,
  reviewQueue: ReviewQueue,
  localAIChat: LocalAIChatPage,
  opportunityDetail: OpportunityDetail,
  scraper: Scraper,
  portals: Portals,
  settings: Settings,
};

export default function App() {
  const [route, setRoute] = useState({ page: "dashboard", opportunityId: null });
  const Page = pages[route.page];

  function navigate(page) {
    setRoute({ page, opportunityId: null });
  }

  function openOpportunity(opportunityId) {
    setRoute({ page: "opportunityDetail", opportunityId });
  }

  return (
    <Layout currentPage={route.page} onNavigate={navigate}>
      <Page
        opportunityId={route.opportunityId}
        onOpenOpportunity={openOpportunity}
      />
    </Layout>
  );
}
