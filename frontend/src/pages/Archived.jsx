import { useCallback, useEffect, useState } from "react";

import { archivePastDeadlines, getReviewQueue, reviewOpportunity } from "../api.js";
import LoadError from "../components/LoadError.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

const errorMessage = "Failed to load archived opportunities. Is the backend running?";

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleDateString();
}

export default function Archived({ onOpenOpportunity }) {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [busyId, setBusyId] = useState(null);
  const [archiving, setArchiving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      // The backend hides Archived from every other view; asking for it
      // explicitly is the only way to list these rows.
      const result = await getReviewQueue({
        status: "Archived",
        sort: "deadline",
        direction: "desc",
      });
      setOpportunities(result ?? []);
      setError("");
    } catch (err) {
      setError(err.message || errorMessage);
    } finally {
      setLoading(false);
      setInitialized(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function runArchiveNow() {
    try {
      setArchiving(true);
      setMessage("Archiving expired opportunities...");
      const result = await archivePastDeadlines();
      setMessage(
        `Archived ${result.archived_count} newly-expired opportunity(ies).`,
      );
      setError("");
      await load();
    } catch (err) {
      setError(err.message || "Failed to archive expired opportunities.");
    } finally {
      setArchiving(false);
    }
  }

  async function restore(id) {
    try {
      setBusyId(id);
      // Restore drops the row back into the working queue for re-triage; the
      // due date is often stale, so it lands in "Needs Review" rather than "New".
      await reviewOpportunity(id, { review_status: "Needs Review" });
      setMessage(`Opportunity ${id} restored to Needs Review.`);
      setError("");
      await load();
    } catch (err) {
      setError(err.message || `Failed to restore opportunity ${id}.`);
    } finally {
      setBusyId(null);
    }
  }

  if (!initialized) {
    return <p>Loading...</p>;
  }

  return (
    <section>
      <h1>Archived</h1>
      <p className="muted-text">
        Opportunities whose submission deadline has passed are archived
        automatically and hidden from the dashboard and review queue. Nothing is
        deleted — restore an item to move it back into the working queue.
      </p>

      <div className="review-toolbar">
        <button
          type="button"
          disabled={archiving}
          aria-busy={archiving}
          onClick={runArchiveNow}
        >
          {archiving ? "Archiving…" : "Archive expired now"}
        </button>
      </div>

      {message ? (
        <p role="status" aria-live="polite">
          {message}
        </p>
      ) : null}
      {error ? <LoadError message={error} onRetry={load} /> : null}

      {!opportunities.length ? (
        <p>No archived opportunities.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Agency / Source</th>
              <th>Due</th>
              <th>Deadline Risk</th>
              <th>Status</th>
              <th>Notes</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {opportunities.map((opp) => (
              <tr key={opp.id}>
                <td>
                  <button
                    className="link-button"
                    type="button"
                    onClick={() => onOpenOpportunity(opp.id)}
                  >
                    {opp.title}
                  </button>
                </td>
                <td>{opp.agency || opp.source || ""}</td>
                <td>{formatDate(opp.due_date)}</td>
                <td>{opp.deadline_risk || ""}</td>
                <td>
                  <StatusBadge status={opp.review_status || "Archived"} />
                </td>
                <td className="wrap-cell">{opp.review_notes || ""}</td>
                <td>
                  <button
                    type="button"
                    disabled={busyId === opp.id}
                    onClick={() => restore(opp.id)}
                  >
                    Restore
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
