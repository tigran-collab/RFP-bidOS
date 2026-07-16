import { getKbDashboard } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, useAsync, formatDate } from "./KbShared.jsx";

const CARDS = [
  { key: "source_documents", label: "Source Documents" },
  { key: "approved_claims", label: "Approved Claims" },
  { key: "pending_review", label: "Pending Review" },
  { key: "expired_items", label: "Expired" },
  { key: "expiring_soon", label: "Expiring Soon" },
  { key: "conflicting_claims", label: "Conflicts" },
  { key: "approved_answers", label: "Approved Answers" },
  { key: "documents_failed", label: "Failed Processing" },
];

export default function KnowledgeDashboard({ onNavigate }) {
  const { data, loading, error, reload } = useAsync(() => getKbDashboard(), []);

  if (error) {
    return (
      <KbPage current="kbDashboard" onNavigate={onNavigate} onUserChange={reload} title="Knowledge Dashboard">
        <LoadError message={error} onRetry={reload} />
      </KbPage>
    );
  }

  const counts = data?.counts || {};
  const coverage = data?.coverage_by_category || [];
  const recent = data?.recent_responses || [];
  const failed = data?.failed_documents || [];
  const conflicts = data?.open_conflicts || [];
  const expiring = data?.expiring_items || [];

  return (
    <KbPage current="kbDashboard" onNavigate={onNavigate} onUserChange={reload} title="Knowledge Dashboard">
      {loading ? (
        <p>Loading...</p>
      ) : (
        <>
          <div className="metrics-grid">
            {CARDS.map((card) => (
              <div className="metric" key={card.key}>
                <span>{card.label}</span>
                <strong>{counts[card.key] ?? 0}</strong>
              </div>
            ))}
          </div>

          <h2>Knowledge Coverage by Category</h2>
          <div className="kb-coverage-grid">
            {coverage.map((c) => (
              <div className="kb-coverage-item" key={c.category}>
                <span>{c.category}</span>
                <strong>{c.approved_claims}</strong>
              </div>
            ))}
          </div>

          <h2>Expiring & Expired ({expiring.length})</h2>
          {!expiring.length ? (
            <p className="muted-text">Nothing expiring soon.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr><th>Item</th><th>Kind</th><th>Category</th><th>Expiration</th><th>Status</th></tr>
              </thead>
              <tbody>
                {expiring.slice(0, 15).map((item) => (
                  <tr key={`${item.kind}-${item.id}`}>
                    <td>{item.title}</td>
                    <td>{item.kind}</td>
                    <td>{item.category || ""}</td>
                    <td>{formatDate(item.expiration_date)}</td>
                    <td>{item.expired ? "Expired" : "Expiring"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="kb-two-col">
            <div>
              <h2>Recently Generated Responses</h2>
              {!recent.length ? (
                <p className="muted-text">No responses yet.</p>
              ) : (
                <ul className="needs-action-list">
                  {recent.map((r) => (
                    <li key={r.id}>
                      <button className="link-button" type="button" onClick={() => onNavigate("kbResponses", { id: r.id })}>
                        {r.request_question}
                      </button>
                      <span className="muted-text"> — {r.review_status} · {formatDate(r.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h2>Open Conflicts ({conflicts.length})</h2>
              {!conflicts.length ? (
                <p className="muted-text">No open conflicts.</p>
              ) : (
                <ul className="needs-action-list">
                  {conflicts.slice(0, 8).map((c) => (
                    <li key={c.id}>
                      <button className="link-button" type="button" onClick={() => onNavigate("kbConflicts")}>
                        {c.detail || c.conflict_type}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <h2>Failed Processing ({failed.length})</h2>
              {!failed.length ? (
                <p className="muted-text">None.</p>
              ) : (
                <ul className="needs-action-list">
                  {failed.map((d) => (
                    <li key={d.id}>
                      <button className="link-button" type="button" onClick={() => onNavigate("kbDocumentDetail", { id: d.id })}>
                        {d.title}
                      </button>
                      <span className="muted-text"> — {d.processing_error || "failed"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </>
      )}
    </KbPage>
  );
}
