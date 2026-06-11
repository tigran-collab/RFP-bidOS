import { useEffect, useState } from "react";

import { getHealth, getOperationsDashboard } from "../api.js";
import StatusBadge from "../components/StatusBadge.jsx";

const errorMessage = "Failed to load backend data. Is the backend running?";

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleDateString();
}

const SUMMARY_CARDS = [
  { key: "total_opportunities", label: "Total Opportunities" },
  { key: "new", label: "New" },
  { key: "needs_review", label: "Needs Review" },
  { key: "pursue", label: "Pursue" },
  { key: "watchlist", label: "Watchlist" },
  { key: "documents_pending_download", label: "Pending Docs" },
  { key: "documents_parsed", label: "Parsed Docs" },
  { key: "requirements_extracted", label: "Requirements Extracted" },
];

export default function Dashboard({ onOpenOpportunity }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(false);
  const [data, setData] = useState(null);

  useEffect(() => {
    async function loadDashboard() {
      try {
        setLoading(true);
        const [health, dashboard] = await Promise.all([
          getHealth(),
          getOperationsDashboard(),
        ]);
        setOnline(health.status === "ok");
        setData(dashboard);
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

  const counts = data?.counts || {};
  const openOpportunity = (id) => onOpenOpportunity && onOpenOpportunity(id);

  return (
    <section>
      <h1>RFP BidOS Dashboard</h1>
      <p className="muted-text">
        Backend: <strong>{online ? "Online" : "Offline"}</strong>
      </p>

      <div className="metrics-grid">
        {SUMMARY_CARDS.map((card) => (
          <div className="metric" key={card.key}>
            <span>{card.label}</span>
            <strong>{counts[card.key] ?? 0}</strong>
          </div>
        ))}
      </div>

      <h2>Upcoming Deadlines (next 30 days)</h2>
      {!data.upcoming_deadlines.length ? (
        <p>No upcoming deadlines.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Agency</th>
              <th>Due</th>
              <th>Deadline Risk</th>
              <th>Review</th>
              <th>Bid Score</th>
              <th>AI Rec</th>
              <th>Next Action</th>
            </tr>
          </thead>
          <tbody>
            {data.upcoming_deadlines.map((item) => (
              <tr key={item.id}>
                <td>
                  <button
                    className="link-button"
                    type="button"
                    onClick={() => openOpportunity(item.id)}
                  >
                    {item.title}
                  </button>
                </td>
                <td>{item.agency || ""}</td>
                <td>{formatDate(item.due_date)}</td>
                <td>{item.deadline_risk || ""}</td>
                <td>
                  <StatusBadge status={item.review_status} />
                </td>
                <td>{item.bid_score ?? ""}</td>
                <td>{item.ai_recommendation || ""}</td>
                <td>{item.next_action || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Top Opportunities</h2>
      {!data.top_opportunities.length ? (
        <p>No opportunities yet.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Agency</th>
              <th>Review</th>
              <th>Bid Score</th>
              <th>AI Rec</th>
              <th>Due</th>
            </tr>
          </thead>
          <tbody>
            {data.top_opportunities.map((item) => (
              <tr key={item.id}>
                <td>
                  <button
                    className="link-button"
                    type="button"
                    onClick={() => openOpportunity(item.id)}
                  >
                    {item.title}
                  </button>
                </td>
                <td>{item.agency || ""}</td>
                <td>
                  <StatusBadge status={item.review_status} />
                </td>
                <td>{item.bid_score ?? ""}</td>
                <td>{item.ai_recommendation || ""}</td>
                <td>{formatDate(item.due_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Needs Action</h2>
      {!data.needs_action.length ? (
        <p>Nothing needs action right now.</p>
      ) : (
        <ul className="needs-action-list">
          {data.needs_action.slice(0, 15).map((item) => (
            <li key={item.id}>
              <button
                className="link-button"
                type="button"
                onClick={() => openOpportunity(item.id)}
              >
                {item.title}
              </button>
              <span className="muted-text">
                {" "}
                — {item.reason}
                {item.suggested_action ? ` → ${item.suggested_action}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h2>Source Health</h2>
      {!data.source_health.length ? (
        <p>No sources configured.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>State</th>
              <th>Portal</th>
              <th>Enabled</th>
              <th>Credentials</th>
              <th>Auth Status</th>
              <th>Last Scrape</th>
            </tr>
          </thead>
          <tbody>
            {data.source_health.map((source) => (
              <tr key={source.id}>
                <td>{source.name}</td>
                <td>{source.state || ""}</td>
                <td>{source.portal_type || ""}</td>
                <td>{source.enabled ? "Yes" : "No"}</td>
                <td>{source.requires_credentials ? "Required" : "Public"}</td>
                <td>{source.auth_status || ""}</td>
                <td>{source.last_scrape_status || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
