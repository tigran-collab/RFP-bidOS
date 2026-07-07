import { useCallback, useEffect, useRef, useState } from "react";

import {
  getReviewQueue,
  prioritizeAll,
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
const DEADLINE_RISKS = [
  "High",
  "Medium",
  "Low",
  "Past Due",
  "Missing Deadline",
  "Needs Review",
];
const QA_RISKS = ["Low", "Medium", "High", "Disqualifying"];

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleDateString();
}

export default function ReviewQueue({ onOpenOpportunity }) {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [initialized, setInitialized] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState("");
  const [priorityFilter, setPriorityFilter] = useState("");
  const [deadlineRiskFilter, setDeadlineRiskFilter] = useState("");
  const [qaRiskFilter, setQaRiskFilter] = useState("");
  const [sortField, setSortField] = useState("priority");
  const [sortDirection, setSortDirection] = useState("desc");
  const [selected, setSelected] = useState(() => new Set());
  const [notesDraft, setNotesDraft] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const requestSeq = useRef(0);
  const dirtyNotes = useRef(new Set());

  const loadQueue = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      setLoading(true);
      const result = await getReviewQueue({
        status: statusFilter,
        priority: priorityFilter,
        deadline_risk: deadlineRiskFilter,
        qa_risk: qaRiskFilter,
        sort: sortField,
        direction: sortDirection,
      });
      if (seq !== requestSeq.current) {
        return;
      }
      setOpportunities(result);
      setNotesDraft((current) =>
        Object.fromEntries(
          result.map((o) => [
            o.id,
            dirtyNotes.current.has(o.id)
              ? current[o.id] ?? o.review_notes ?? ""
              : o.review_notes || "",
          ]),
        ),
      );
      setError("");
    } catch {
      if (seq === requestSeq.current) {
        setError(errorMessage);
      }
    } finally {
      if (seq === requestSeq.current) {
        setLoading(false);
        setInitialized(true);
      }
    }
  }, [statusFilter, priorityFilter, deadlineRiskFilter, qaRiskFilter, sortField, sortDirection]);

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
      return true;
    } catch {
      setError(`Failed to update opportunity ${id}.`);
      return false;
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
          `${parts.join(", ")} -> next: ${result.next_action}${errSuffix}`,
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
    if (!ids.length || bulkBusy) {
      return;
    }
    try {
      setBulkBusy(true);
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
    } finally {
      setBulkBusy(false);
    }
  }

  async function saveNote(id) {
    const saved = await applyReview(
      id,
      { review_notes: notesDraft[id] || "" },
      "notes saved",
    );
    if (saved) {
      dirtyNotes.current.delete(id);
    }
  }

  async function recomputePriorities() {
    try {
      setMessage("Recomputing priorities...");
      const result = await prioritizeAll();
      setMessage(`Priorities recomputed for ${result.updated} opportunity(ies).`);
      setError("");
      await loadQueue();
    } catch (err) {
      setError(err.message || "Failed to recompute priorities.");
    }
  }

  if (!initialized) {
    return <p>Loading...</p>;
  }

  return (
    <section>
      <h1>Review Queue</h1>
      <div className="review-toolbar">
        <button type="button" onClick={recomputePriorities}>
          Recompute priorities
        </button>
      </div>
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
        <label>
          Deadline risk
          <select
            value={deadlineRiskFilter}
            onChange={(event) => setDeadlineRiskFilter(event.target.value)}
          >
            <option value="">All</option>
            {DEADLINE_RISKS.map((risk) => (
              <option key={risk} value={risk}>
                {risk}
              </option>
            ))}
          </select>
        </label>
        <label>
          QA risk
          <select
            value={qaRiskFilter}
            onChange={(event) => setQaRiskFilter(event.target.value)}
          >
            <option value="">All</option>
            {QA_RISKS.map((risk) => (
              <option key={risk} value={risk}>
                {risk}
              </option>
            ))}
          </select>
        </label>
        <label>
          Sort by
          <select
            value={sortField}
            onChange={(event) => setSortField(event.target.value)}
          >
            <option value="priority">Priority</option>
            <option value="score">Bid score</option>
            <option value="relevance">Relevance</option>
            <option value="deadline">Deadline</option>
            <option value="created">Recently added</option>
            <option value="default">Default</option>
          </select>
        </label>
        <label>
          Direction
          <select
            value={sortDirection}
            onChange={(event) => setSortDirection(event.target.value)}
          >
            <option value="desc">Descending</option>
            <option value="asc">Ascending</option>
          </select>
        </label>
      </div>

      {selected.size ? (
        <div className="bulk-actions">
          <span>{selected.size} selected:</span>
          <button
            type="button"
            disabled={bulkBusy}
            onClick={() => bulkMark("Do Not Pursue")}
          >
            Do Not Pursue
          </button>
          <button
            type="button"
            disabled={bulkBusy}
            onClick={() => bulkMark("Watchlist")}
          >
            Watchlist
          </button>
          <button
            type="button"
            disabled={bulkBusy}
            onClick={() => bulkMark("Archived")}
          >
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
              <th>Priority</th>
              <th>Title</th>
              <th>Agency / Source</th>
              <th>Due</th>
              <th>Deadline Risk</th>
              <th>QA</th>
              <th>Submission</th>
              <th>Bid Score</th>
              <th>Relevance</th>
              <th>AI Rec</th>
              <th>Status</th>
              <th>Set Priority</th>
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
                    aria-label={`Select ${opp.title}`}
                    onChange={() => toggleSelected(opp.id)}
                  />
                </td>
                <td className="priority-cell">
                  {opp.priority_tier
                    ? `${opp.priority_tier}${
                        opp.priority_rank !== null &&
                        opp.priority_rank !== undefined
                          ? ` (${Math.round(opp.priority_rank)})`
                          : ""
                      }`
                    : ""}
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
                <td>{opp.deadline_risk || ""}</td>
                <td>
                  {opp.logistics_qa_status
                    ? `${opp.logistics_qa_status} / ${opp.logistics_qa_risk}`
                    : ""}
                </td>
                <td>{opp.submission_method || ""}</td>
                <td>{opp.bid_score ?? ""}</td>
                <td>
                  {opp.relevance_decision || ""}
                  {opp.relevance_score !== null && opp.relevance_score !== undefined
                    ? ` (${opp.relevance_score})`
                    : ""}
                  {opp.as_needed_warning ? (
                    <div className="notice-text">As-needed caution</div>
                  ) : null}
                </td>
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
                    <select
                      value={opp.review_status || "New"}
                      disabled={busyId === opp.id}
                      aria-label={`Set review status for ${opp.title}`}
                      onChange={(event) =>
                        applyReview(
                          opp.id,
                          { review_status: event.target.value },
                          event.target.value,
                        )
                      }
                    >
                      {REVIEW_STATUSES.map((status) => (
                        <option key={status} value={status}>
                          {status}
                        </option>
                      ))}
                    </select>
                  </div>
                </td>
                <td>
                  <div className="review-notes">
                    <input
                      type="text"
                      value={notesDraft[opp.id] ?? ""}
                      placeholder="Review notes"
                      onChange={(event) => {
                        dirtyNotes.current.add(opp.id);
                        setNotesDraft((current) => ({
                          ...current,
                          [opp.id]: event.target.value,
                        }));
                      }}
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
