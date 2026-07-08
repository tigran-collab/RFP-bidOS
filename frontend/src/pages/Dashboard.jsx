import { useCallback, useEffect, useState } from "react";

import {
  API_BASE_URL,
  getAiStatus,
  getDashboardDigest,
  getHealth,
  getOperationsDashboard,
} from "../api.js";
import LoadError from "../components/LoadError.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

const EXPORTS = [
  { label: "Export Opportunities CSV", path: "/exports/opportunities.csv" },
  { label: "Export Requirements CSV", path: "/exports/requirements.csv" },
  { label: "Export Documents CSV", path: "/exports/documents.csv" },
  { label: "Export Logistics QA CSV", path: "/exports/logistics-qa.csv" },
  { label: "Export Deadlines (.ics)", path: "/exports/deadlines.ics" },
];

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

function DigestBucket({ title, count, items = [], onOpen, meta }) {
  return (
    <div className="digest-bucket">
      <div className="digest-bucket-head">
        <span>{title}</span>
        <strong>{count}</strong>
      </div>
      {items.length ? (
        <ul className="digest-list">
          {items.slice(0, 6).map((item) => (
            <li key={item.id}>
              <button
                className="link-button"
                type="button"
                onClick={() => onOpen(item.id)}
              >
                {item.title}
              </button>
              {meta && meta(item) ? (
                <span className="muted-text"> — {meta(item)}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted-text">Nothing here.</p>
      )}
    </div>
  );
}

export default function Dashboard({ onOpenOpportunity }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(false);
  const [aiStatus, setAiStatus] = useState(null);
  const [data, setData] = useState(null);
  const [digest, setDigest] = useState(null);

  const loadDashboard = useCallback(async () => {
    try {
      setLoading(true);
      const [health, dashboard, ai, digestResult] = await Promise.all([
        getHealth(),
        getOperationsDashboard(),
        getAiStatus(),
        getDashboardDigest(),
      ]);
      setOnline(health.status === "ok");
      setData(dashboard);
      setAiStatus(ai);
      setDigest(digestResult);
      setError("");
    } catch (err) {
      setOnline(false);
      setError(err.message || errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <LoadError message={error} onRetry={loadDashboard} />;
  }

  // Local AI is only truly usable when the configured model is actually pulled.
  const configuredModel = aiStatus?.model || "qwen3:8b";
  const installedModels = Array.isArray(aiStatus?.models)
    ? aiStatus.models
        .map((m) => m?.name || m?.model)
        .filter(Boolean)
    : [];
  const modelInstalled =
    !aiStatus?.available || installedModels.includes(configuredModel);

  const counts = data?.counts || {};
  const {
    upcoming_deadlines = [],
    top_opportunities = [],
    needs_action = [],
    source_health = [],
  } = data || {};
  const openOpportunity = (id) => onOpenOpportunity && onOpenOpportunity(id);

  return (
    <section>
      <h1>RFP BidOS Dashboard</h1>
      <p className="muted-text">
        Backend: <strong>{online ? "Online" : "Offline"}</strong>
      </p>
      <p className="muted-text">
        Local AI:{" "}
        <strong>
          {!aiStatus?.available
            ? "Unavailable"
            : modelInstalled
              ? "Available"
              : `Model not installed — run: ollama pull ${configuredModel}`}
        </strong>
        {" | Model: "}
        <strong>{configuredModel}</strong>
      </p>

      <div className="metrics-grid">
        {SUMMARY_CARDS.map((card) => (
          <div className="metric" key={card.key}>
            <span>{card.label}</span>
            <strong>{counts[card.key] ?? 0}</strong>
          </div>
        ))}
      </div>

      {digest ? (
        <>
          <h2>Daily Digest — What changed (last {digest.days} days)</h2>
          <div className="digest-grid">
            <DigestBucket
              title="New"
              count={digest.counts?.new_opportunities ?? 0}
              items={digest.new_opportunities}
              onOpen={openOpportunity}
              meta={(item) => item.agency || item.relevance_decision || ""}
            />
            <DigestBucket
              title="Upcoming deadlines"
              count={digest.counts?.upcoming_deadlines ?? 0}
              items={digest.upcoming_deadlines}
              onOpen={openOpportunity}
              meta={(item) =>
                item.days_until === 0
                  ? "due today"
                  : item.days_until > 0
                    ? `in ${item.days_until} day(s)`
                    : formatDate(item.due_date)
              }
            />
            <DigestBucket
              title="At risk"
              count={digest.counts?.at_risk ?? 0}
              items={digest.at_risk}
              onOpen={openOpportunity}
              meta={(item) =>
                item.days_until !== null && item.days_until < 0
                  ? `${Math.abs(item.days_until)} day(s) ago`
                  : item.deadline_risk || "high risk"
              }
            />
          </div>
        </>
      ) : null}

      <h2>Exports</h2>
      <div className="export-buttons">
        {EXPORTS.map((item) => (
          <a
            key={item.path}
            className="secondary-button"
            href={`${API_BASE_URL}${item.path}`}
          >
            {item.label}
          </a>
        ))}
      </div>

      <h2>Upcoming Deadlines (next 30 days)</h2>
      {!upcoming_deadlines.length ? (
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
            {upcoming_deadlines.map((item) => (
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
      {!top_opportunities.length ? (
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
            {top_opportunities.map((item) => (
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
      {!needs_action.length ? (
        <p>Nothing needs action right now.</p>
      ) : (
        <ul className="needs-action-list">
          {needs_action.slice(0, 15).map((item) => (
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
                - {item.reason}
                {item.suggested_action ? ` -> ${item.suggested_action}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}

      <h2>Source Health</h2>
      {!source_health.length ? (
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
            {source_health.map((source) => (
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
