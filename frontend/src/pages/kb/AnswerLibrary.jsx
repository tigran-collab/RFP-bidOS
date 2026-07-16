import { useState } from "react";

import { getKbAnswers } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function AnswerLibrary({ onNavigate }) {
  const meta = useKbMeta();
  const [filters, setFilters] = useState({});
  const { data, loading, error, reload } = useAsync(
    () => getKbAnswers(filters),
    [JSON.stringify(filters)],
  );
  const answers = data || [];

  return (
    <KbPage
      current="kbAnswers"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Reusable Answer Library"
      actions={
        <button className="primary-button" type="button" onClick={() => onNavigate("kbAnswerEditor", {})}>
          New Answer
        </button>
      }
    >
      <div className="kb-filters">
        <label>
          Status
          <select value={filters.status || ""} onChange={(e) => setFilters({ ...filters, status: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.answer_statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Category
          <select value={filters.category || ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.answer_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      </div>

      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : !answers.length ? (
        <p className="muted-text">No reusable answers yet.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Question</th><th>Category</th><th>Status</th><th>Usage</th><th>Last Used</th><th>Expiration</th></tr>
          </thead>
          <tbody>
            {answers.map((a) => (
              <tr key={a.id}>
                <td>
                  <button className="link-button" type="button" onClick={() => onNavigate("kbAnswerEditor", { id: a.id })}>
                    {a.question_title}
                  </button>
                </td>
                <td>{a.category || ""}</td>
                <td><StatusBadge status={a.status} /></td>
                <td>{a.usage_count}</td>
                <td>{formatDate(a.last_used_at)}</td>
                <td>{formatDate(a.expiration_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </KbPage>
  );
}
