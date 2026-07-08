import { useCallback, useEffect, useMemo, useState } from "react";

import { getOpportunities } from "../api.js";
import LoadError from "../components/LoadError.jsx";
import OpportunityTable from "../components/OpportunityTable.jsx";

const errorMessage = "Failed to load backend data. Is the backend running?";

const REVIEW_STATUSES = [
  "New",
  "Needs Review",
  "Pursue",
  "Do Not Pursue",
  "Watchlist",
  "Archived",
];

const SORTS = [
  { value: "due_asc", label: "Due date (soonest)" },
  { value: "score_desc", label: "Bid score (highest)" },
  { value: "recent", label: "Recently added" },
];

const PAGE_SIZE = 50;

// Push blank/undefined dates to the end for an ascending due-date sort.
function dueTime(value) {
  if (!value) return Number.POSITIVE_INFINITY;
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? Number.POSITIVE_INFINITY : time;
}

function addedTime(o) {
  const value = o.created_at || o.updated_at;
  const time = value ? new Date(value).getTime() : NaN;
  if (!Number.isNaN(time)) return time;
  // Fall back to id (monotonic insertion order) when timestamps are absent.
  return o.id ?? 0;
}

export default function Opportunities({ onOpenOpportunity }) {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sort, setSort] = useState("due_asc");
  const [page, setPage] = useState(1);

  const loadOpportunities = useCallback(async () => {
    try {
      setLoading(true);
      setOpportunities((await getOpportunities()) ?? []);
      setError("");
    } catch (err) {
      setError(err.message || errorMessage);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOpportunities();
  }, [loadOpportunities]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    let rows = opportunities;
    if (term) {
      rows = rows.filter((o) =>
        [o.title, o.agency, o.solicitation_number]
          .filter(Boolean)
          .some((field) => String(field).toLowerCase().includes(term)),
      );
    }
    if (statusFilter) {
      rows = rows.filter((o) => (o.review_status || "New") === statusFilter);
    }
    const sorted = [...rows];
    if (sort === "due_asc") {
      sorted.sort((a, b) => dueTime(a.due_date) - dueTime(b.due_date));
    } else if (sort === "score_desc") {
      sorted.sort(
        (a, b) => (b.bid_score ?? -Infinity) - (a.bid_score ?? -Infinity),
      );
    } else if (sort === "recent") {
      sorted.sort((a, b) => addedTime(b) - addedTime(a));
    }
    return sorted;
  }, [opportunities, search, statusFilter, sort]);

  // Reset to the first page whenever the result set changes.
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, sort]);

  const total = filtered.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const start = (currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <LoadError message={error} onRetry={loadOpportunities} />;
  }

  return (
    <section>
      <h1>Opportunities</h1>
      <div className="review-filters">
        <label>
          Search
          <input
            type="text"
            value={search}
            placeholder="Title, agency, or solicitation #"
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
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
          Sort by
          <select value={sort} onChange={(event) => setSort(event.target.value)}>
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="muted-text">
        {total === opportunities.length
          ? `${total} opportunit${total === 1 ? "y" : "ies"}`
          : `Showing ${total} of ${opportunities.length} opportunities`}
        {pageCount > 1
          ? ` — page ${currentPage} of ${pageCount}`
          : ""}
      </p>

      <OpportunityTable
        opportunities={visible}
        onOpenOpportunity={onOpenOpportunity}
      />

      {pageCount > 1 ? (
        <div className="button-row" style={{ marginTop: "1rem" }}>
          <button
            className="secondary-button"
            type="button"
            disabled={currentPage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={currentPage >= pageCount}
            onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
          >
            Next
          </button>
        </div>
      ) : null}
    </section>
  );
}
