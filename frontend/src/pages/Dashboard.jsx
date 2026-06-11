import { useEffect, useState } from "react";

import { getHealth, getOpportunities } from "../api.js";
import OpportunityTable from "../components/OpportunityTable.jsx";

const errorMessage = "Failed to load backend data. Is the backend running?";

function normalizeDecision(value) {
  return (value || "").toLowerCase().replaceAll("_", "-").trim();
}

export default function Dashboard({ onOpenOpportunity }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(false);
  const [opportunities, setOpportunities] = useState([]);

  useEffect(() => {
    async function loadDashboard() {
      try {
        setLoading(true);
        const [health, opportunityData] = await Promise.all([
          getHealth(),
          getOpportunities(),
        ]);
        setOnline(health.status === "ok");
        setOpportunities(opportunityData);
        setError("");
      } catch {
        setOnline(false);
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
  }, []);

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  const bidCount = opportunities.filter(
    (item) => normalizeDecision(item.bid_decision) === "bid",
  ).length;
  const conditionalBidCount = opportunities.filter((item) =>
    ["conditional", "conditional-bid"].includes(
      normalizeDecision(item.bid_decision),
    ),
  ).length;
  const noBidCount = opportunities.filter((item) =>
    ["no-bid", "nobid"].includes(normalizeDecision(item.bid_decision)),
  ).length;
  const needsReviewCount = opportunities.filter((item) =>
    ["review", "needs-review"].includes(normalizeDecision(item.bid_decision)),
  ).length;
  const recentOpportunities = opportunities.slice(0, 5);

  return (
    <section>
      <h1>RFP BidOS Dashboard</h1>
      <div className="metrics-grid">
        <div className="metric">
          <span>Backend connection status</span>
          <strong>{online ? "Online" : "Offline"}</strong>
        </div>
        <div className="metric">
          <span>Total opportunities</span>
          <strong>{opportunities.length}</strong>
        </div>
        <div className="metric">
          <span>Bid count</span>
          <strong>{bidCount}</strong>
        </div>
        <div className="metric">
          <span>Conditional Bid count</span>
          <strong>{conditionalBidCount}</strong>
        </div>
        <div className="metric">
          <span>No Bid count</span>
          <strong>{noBidCount}</strong>
        </div>
        <div className="metric">
          <span>Needs Review count</span>
          <strong>{needsReviewCount}</strong>
        </div>
      </div>

      <h2>Recent opportunities</h2>
      <OpportunityTable
        opportunities={recentOpportunities}
        onOpenOpportunity={onOpenOpportunity}
      />
    </section>
  );
}
