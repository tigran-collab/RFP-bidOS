import { useState } from "react";

import Layout from "./components/Layout.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import OpportunityDetail from "./pages/OpportunityDetail.jsx";
import Opportunities from "./pages/Opportunities.jsx";
import NewOpportunity from "./pages/NewOpportunity.jsx";
import ReviewQueue from "./pages/ReviewQueue.jsx";
import Archived from "./pages/Archived.jsx";
import Scraper from "./pages/Scraper.jsx";
import Portals from "./pages/Portals.jsx";
import Settings from "./pages/Settings.jsx";
import KnowledgeDashboard from "./pages/kb/KnowledgeDashboard.jsx";
import DocumentVault from "./pages/kb/DocumentVault.jsx";
import DocumentDetail from "./pages/kb/DocumentDetail.jsx";
import Gallery from "./pages/kb/Gallery.jsx";
import ClaimsRegistry from "./pages/kb/ClaimsRegistry.jsx";
import ClaimDetail from "./pages/kb/ClaimDetail.jsx";
import AnswerLibrary from "./pages/kb/AnswerLibrary.jsx";
import AnswerEditor from "./pages/kb/AnswerEditor.jsx";
import ResponseWorkspace from "./pages/kb/ResponseWorkspace.jsx";
import ResponseReview from "./pages/kb/ResponseReview.jsx";
import ConflictQueue from "./pages/kb/ConflictQueue.jsx";
import ExpirationQueue from "./pages/kb/ExpirationQueue.jsx";
import KbAdminSettings from "./pages/kb/KbAdminSettings.jsx";

const pages = {
  dashboard: Dashboard,
  opportunities: Opportunities,
  newOpportunity: NewOpportunity,
  reviewQueue: ReviewQueue,
  archived: Archived,
  opportunityDetail: OpportunityDetail,
  scraper: Scraper,
  portals: Portals,
  settings: Settings,
  // Knowledge Base
  kbDashboard: KnowledgeDashboard,
  kbDocuments: DocumentVault,
  kbDocumentDetail: DocumentDetail,
  kbGallery: Gallery,
  kbClaims: ClaimsRegistry,
  kbClaimDetail: ClaimDetail,
  kbAnswers: AnswerLibrary,
  kbAnswerEditor: AnswerEditor,
  kbWorkspace: ResponseWorkspace,
  kbResponses: ResponseReview,
  kbConflicts: ConflictQueue,
  kbExpirations: ExpirationQueue,
  kbAdmin: KbAdminSettings,
};

export default function App() {
  const [route, setRoute] = useState({ page: "dashboard", params: {} });
  const Page = pages[route.page] || Dashboard;

  function navigate(page, params = {}) {
    setRoute({ page, params });
  }

  function openOpportunity(opportunityId) {
    setRoute({ page: "opportunityDetail", params: { opportunityId } });
  }

  return (
    <Layout currentPage={route.page} onNavigate={navigate}>
      <Page
        opportunityId={route.params?.opportunityId ?? null}
        params={route.params || {}}
        onOpenOpportunity={openOpportunity}
        onNavigate={navigate}
      />
    </Layout>
  );
}
