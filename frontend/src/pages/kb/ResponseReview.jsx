import { useState } from "react";

import { getKbResponse, getKbResponses, updateKbResponse } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, Warnings, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function ResponseReview({ params, onNavigate }) {
  const id = params?.id;
  if (id) {
    return <ResponseDetail id={id} onNavigate={onNavigate} />;
  }
  return <ResponseList onNavigate={onNavigate} />;
}

function ResponseList({ onNavigate }) {
  const meta = useKbMeta();
  const [filters, setFilters] = useState({});
  const { data, loading, error, reload } = useAsync(
    () => getKbResponses(filters),
    [JSON.stringify(filters)],
  );
  const responses = data || [];

  return (
    <KbPage current="kbResponses" onNavigate={onNavigate} onUserChange={reload} title="Generated Responses">
      <div className="kb-filters">
        <label>
          Review Status
          <select value={filters.review_status || ""} onChange={(e) => setFilters({ ...filters, review_status: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.response_review_statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : !responses.length ? (
        <p className="muted-text">No responses. Draft one in the Workspace.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Question</th><th>Category</th><th>Confidence</th><th>Review</th><th>Opportunity</th><th>Created</th></tr>
          </thead>
          <tbody>
            {responses.map((r) => (
              <tr key={r.id}>
                <td>
                  <button className="link-button" type="button" onClick={() => onNavigate("kbResponses", { id: r.id })}>
                    {r.request_question}
                  </button>
                </td>
                <td>{r.category || ""}</td>
                <td>{r.confidence_score != null ? Math.round(r.confidence_score * 100) + "%" : ""}</td>
                <td><StatusBadge status={r.review_status} /></td>
                <td>{r.opportunity_id ? `#${r.opportunity_id}` : ""}</td>
                <td>{formatDate(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </KbPage>
  );
}

function ResponseDetail({ id, onNavigate }) {
  const meta = useKbMeta();
  const { data, loading, error, reload } = useAsync(() => getKbResponse(id), [id]);
  const [msg, setMsg] = useState("");

  async function setReviewStatus(status) {
    try {
      await updateKbResponse(id, { review_status: status });
      setMsg(`Marked ${status}.`);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const response = data?.response;
  const citations = data?.citations || [];

  return (
    <KbPage
      current="kbResponses"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Response Review"
      actions={
        <>
          <button className="secondary-button" type="button" onClick={() => onNavigate("kbResponses")}>← All Responses</button>
          {response ? (meta?.response_review_statuses || []).map((s) => (
            <button key={s} className="secondary-button" type="button" onClick={() => setReviewStatus(s)}>{s}</button>
          )) : null}
        </>
      }
    >
      {msg ? <p className="notice-text">{msg}</p> : null}
      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading || !response ? (
        <p>Loading...</p>
      ) : (
        <div className="kb-two-col">
          <div>
            <p className="muted-text">
              {response.category} · <StatusBadge status={response.review_status} /> · confidence{" "}
              {response.confidence_score != null ? Math.round(response.confidence_score * 100) + "%" : "—"}
            </p>
            <h2>Question</h2>
            <p>{response.request_question}</p>
            <h2>Drafted Response</h2>
            <div className="kb-response-text">{response.response_text}</div>
            <h2>Warnings</h2>
            <Warnings warnings={response.warnings} />
          </div>
          <div>
            <h2>Citations ({citations.length})</h2>
            {!citations.length ? (
              <p className="muted-text">No citations.</p>
            ) : (
              citations.map((c) => (
                <div className="kb-citation" key={c.id}>
                  <span className="kb-citation-marker">{c.marker}</span>
                  {c.claim_id ? (
                    <button className="link-button" type="button" onClick={() => onNavigate("kbClaimDetail", { id: c.claim_id })}>Claim {c.claim_id}</button>
                  ) : null}
                  {c.document_id ? (
                    <button className="link-button" type="button" style={{ marginLeft: "0.4rem" }} onClick={() => onNavigate("kbDocumentDetail", { id: c.document_id })}>
                      Doc {c.document_id}{c.page_number ? ` p.${c.page_number}` : ""}
                    </button>
                  ) : null}
                  {c.approval_status ? <span className="muted-text"> · {c.approval_status}</span> : null}
                  {c.excerpt ? <div className="muted-text">{c.excerpt}</div> : null}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </KbPage>
  );
}
