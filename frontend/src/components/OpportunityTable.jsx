import StatusBadge from "./StatusBadge.jsx";

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleDateString();
}

export default function OpportunityTable({ opportunities = [], onOpenOpportunity }) {
  if (!opportunities?.length) {
    return <p>No opportunities found.</p>;
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Title</th>
          <th>Agency</th>
          <th>Source</th>
          <th>Due Date</th>
          <th>Bid Decision</th>
          <th>Bid Score</th>
          <th>Relevance</th>
          <th>AI Recommendation</th>
          <th>AI Score</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {opportunities.map((opportunity) => (
          <tr key={opportunity.id}>
            <td>
              <button
                className="link-button"
                type="button"
                onClick={() => onOpenOpportunity(opportunity.id)}
              >
                {opportunity.title}
              </button>
            </td>
            <td>{opportunity.agency || ""}</td>
            <td>{opportunity.source || ""}</td>
            <td>{formatDate(opportunity.due_date)}</td>
            <td>{opportunity.bid_decision || ""}</td>
            <td>{opportunity.bid_score ?? ""}</td>
            <td>
              {opportunity.relevance_decision || ""}
              {opportunity.relevance_score !== null && opportunity.relevance_score !== undefined
                ? ` (${opportunity.relevance_score})`
                : ""}
              {opportunity.as_needed_warning ? (
                <div className="notice-text">As-needed caution</div>
              ) : null}
            </td>
            <td>{opportunity.ai_recommendation || ""}</td>
            <td>{opportunity.ai_score ?? ""}</td>
            <td>
              <StatusBadge status={opportunity.status || "unknown"} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
