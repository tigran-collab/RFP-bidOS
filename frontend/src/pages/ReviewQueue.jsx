import { useCallback, useEffect, useState } from "react";

import {
  aiEvaluateOpportunity,
  downloadOpportunityDocuments,
  extractOpportunityRequirements,
  getReviewQueue,
  reviewOpportunity,
  runPursuitPrep,
} from "../api.js";
import StatusBadge from "../components/StatusBadge.jsx";

const errorMessage = "Failed to load review queue. Is the backend running?";

const REVIEW_STATUSES = [
  "New",
  "Needs Review",
  "Pursue",
  "Do Not Pursue",
  "Watchlist",
  "Archived",
];
const PRIORITIES = ["High", "Medium", "Low"];

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleDateString();
}

export default function ReviewQueue({ onOpenOpportunity }) {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [notesDraft, setNotesDraft] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const loadQueue = useCallback(async () => {
    try {
      setLoading(true);
      const result = await getReviewQueue({
        status: statusFilter,
        priority: priorityFilter,
      });
      setOpportunities(result);
      setNotesDraft(
        Object.fromEntries(result.map((o) => [o.id, o.review_notes || ""])),
      );
      setError("");
    } catch {
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, priorityFilter]);

  useEffect(() => {
    loadQueue();
  }, [loadQueue]);

  async function applyReview(id, payload, label) {
    try {
      setBusyId(id);
      await reviewOpportunity(id, payload);
      setMessage(`Opportunity ${id}: ${label}`);
      setError("");
      await loadQueue();
    } catch {
      setError(`Failed to update opportunity ${id}.`);
    } finally {
      setBusyId(null);
    }
  }

  async function runAction(id, action, label) {
    try {
      setBusyId(id);
      const result = await action(id);
      const summary =
        result?.downloaded_count !== undefined
          ? `${result.downloaded_count} downloaded, ${result.skipped_count} skipped`
          : result?.requirements_count !== undefined
            ? `${result.requirements_count} requirements`
            : "done";
      setMessage(`Opportunity ${id}: ${label} (${summary})`);
      setError("");
      await loadQueue();
    } catch (err) {
      setError(err.message || `Failed to run ${label} for opportunity ${id}.`);
    } finally {
      setBusyId(null);
    }
  }

  async function runPrep(id) {
    try {
      setBusyId(id);
      setMessage(`Running pursuit prep for opportunity ${id}...`);
      const result = await runPursuitPrep(id);
      const m = result.metrics || {};
      const parts = [
        `${m.documents_discovered ?? 0} discovered`,
        `${m.documents_downloaded ?? 0} downloaded`,
        `${m.documents_parsed ?? 0} parsed`,
        `AI ${m.ai_evaluated ? "ok" : "skipped/failed"}`,
        `${m.requirements_extracted ?? 0} requirements`,
      ];
      const errSuffix = result.errors?.length
        ? ` | errors: ${result.errors.length}`
        : "";
      setMessage(
        `Opportunity ${id} pursuit prep (${result.final_status}): ` +
          `${parts.join(", ")} → next: ${result.next_action}${errSuffix}`,
      );
      setError(result.errors?.length ? result.errors.join("; ") : "");
      await loadQueue();
    } catch (err) {
      setError(err.message || `Failed to run pursuit prep for opportunity ${id}.`);
    } finally {
      setBusyId(null);
    }
  }

  function toggleSelected(id) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  async function bulkMark(status) {
    const ids = [...selected];
    if (!ids.length) {
      return;
    }
    try {
      setMessage(`Marking ${ids.length} as ${status}...`);
      for (const id of ids) {
        await reviewOpportunity(id, { review_status: status });
      }
      setSelected(new Set());
      setMessage(`${ids.length} marked as ${status}.`);
      setError("");
      await loadQueue();
    } catch {
      setError("Bulk update failed.");
    }
  }

  async function saveNote(id) {
    await applyReview(id, { review_notes: notesDraft[id] || "" }, "notes saved");
  }

  if (loading) {
    return <p>Loading...</p>;
  }

  return (
    <section>
      <h1>Review Queue</h1>
      <div className="review-filters">
        <label>
          Review status
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">All</option>
            {REVIEW_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label>
          Priority
          <select
            value={priorityFilter}
            onChange={(event) => setPriorityFilter(event.target.value)}
          >
            <option value="">All</option>
            {PRIORITIES.map((priority) => (
              <option key={priority} value={priority}>
                {priority}
              </option>
            ))}
          </select>
        </label>
      </div>

      {selected.size ? (
        <div className="bulk-actions">
          <span>{selected.size} selected:</span>
          <button type="button" onClick={() => bulkMark("Do Not Pursue")}>
            Do Not Pursue
          </button>
          <button type="button" onClick={() => bulkMark("Watchlist")}>
            Watchlist
          </button>
          <button type="button" onClick={() => bulkMark("Archived")}>
            Archive
          </button>
        </div>
      ) : null}

      {message ? <p>{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}

      {!opportunities.length ? (
        <p>No opportunities match the current filters.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th></th>
              <th>Title</th>
              <th>Agency / Source</th>
              <th>Due</th>
              <th>Bid Score</th>
              <th>AI Rec</th>
              <th>Review</th>
              <th>Priority</th>
              <th>Next Action</th>
              <th>Actions</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {opportunities.map((opp) => (
              <tr key={opp.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(opp.id)}
                    onChange={() => toggleSelected(opp.id)}
                  />
                </td>
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
                <td>{opp.bid_score ?? ""}</td>
                <td>{opp.ai_recommendation || ""}</td>
                <td>
                  <StatusBadge status={opp.review_status || "New"} />
                </td>
                <td>
                  <select
                    value={opp.priority || ""}
                    disabled={busyId === opp.id}
                    onChange={(event) =>
                      applyReview(
                        opp.id,
                        { priority: event.target.value || null },
                        `priority ${event.target.value || "cleared"}`,
                      )
                    }
                  >
                    <option value="">-</option>
                    {PRIORITIES.map((priority) => (
                      <option key={priority} value={priority}>
                        {priority}
                      </option>
                    ))}
                  </select>
                </td>
                <td>{opp.next_action || ""}</td>
                <td>
                  <div className="review-actions">
                    <button
                      type="button"
                      className={
                        ["Pursue", "Watchlist"].includes(opp.review_status)
                          ? "primary-button"
                          : ""
                      }
                      disabled={busyId === opp.id}
                      onClick={() => runPrep(opp.id)}
                    >
                      Run Pursuit Prep
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        applyReview(opp.id, { review_status: "Pursue" }, "Pursue")
                      }
                    >
                      Pursue
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        applyReview(
                          opp.id,
                          { review_status: "Do Not Pursue" },
                          "Do Not Pursue",
                        )
                      }
                    >
                      Do Not Pursue
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        applyReview(opp.id, { review_status: "Watchlist" }, "Watchlist")
                      }
                    >
                      Watchlist
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        applyReview(opp.id, { review_status: "Archived" }, "Archived")
                      }
                    >
                      Archive
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        runAction(opp.id, downloadOpportunityDocuments, "Download Docs")
                      }
                    >
                      Download Docs
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() => runAction(opp.id, aiEvaluateOpportunity, "AI Eval")}
                    >
                      Run AI Eval
                    </button>
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() =>
                        runAction(
                          opp.id,
                          extractOpportunityRequirements,
                          "Extract Requirements",
                        )
                      }
                    >
                      Extract Requirements
                    </button>
                  </div>
                </td>
                <td>
                  <div className="review-notes">
                    <input
                      type="text"
                      value={notesDraft[opp.id] ?? ""}
                      placeholder="Review notes"
                      onChange={(event) =>
                        setNotesDraft((current) => ({
                          ...current,
                          [opp.id]: event.target.value,
                        }))
                      }
                    />
                    <button
                      type="button"
                      disabled={busyId === opp.id}
                      onClick={() => saveNote(opp.id)}
                    >
                      Save
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
