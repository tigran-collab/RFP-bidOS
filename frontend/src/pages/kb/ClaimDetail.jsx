import { useState } from "react";

import { claimAction, getKbClaim, restoreKbClaimVersion, updateKbClaim } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function ClaimDetail({ params, onNavigate }) {
  const id = params?.id;
  const meta = useKbMeta();
  const { data, loading, error, reload } = useAsync(() => getKbClaim(id), [id]);
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [msg, setMsg] = useState("");

  async function act(action) {
    setBusy(action);
    setMsg("");
    try {
      const note = ["reject", "restrict"].includes(action)
        ? window.prompt(`Note for ${action}?`) || ""
        : undefined;
      await claimAction(id, action, note);
      reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy("");
    }
  }

  async function saveEdit() {
    setBusy("save");
    try {
      await updateKbClaim(id, draft);
      setEditing(false);
      reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy("");
    }
  }

  async function restore(versionId) {
    try {
      await restoreKbClaimVersion(id, versionId);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const detail = data;
  const claim = detail?.claim;
  const restricted = detail?.restricted;

  return (
    <KbPage
      current="kbClaimDetail"
      onNavigate={onNavigate}
      onUserChange={reload}
      title={claim ? claim.title : "Claim"}
      actions={
        <>
          <button className="secondary-button" type="button" onClick={() => onNavigate("kbClaims")}>← Registry</button>
          {claim && !restricted ? (
            <>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("approve")}>Approve</button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("reject")}>Reject</button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("restrict")}>Restrict</button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("submit")}>Submit for Review</button>
              <button className="secondary-button" type="button" onClick={() => { setDraft({ canonical_text: claim.canonical_text, short_text: claim.short_text || "", long_text: claim.long_text || "", restrictions: claim.restrictions || "" }); setEditing(true); }}>Edit</button>
            </>
          ) : null}
        </>
      }
    >
      {msg ? <p className="error-text">{msg}</p> : null}
      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading || !claim ? (
        <p>Loading...</p>
      ) : restricted ? (
        <p className="notice-text">This claim is restricted. You do not have permission to view its content.</p>
      ) : editing ? (
        <div className="kb-card">
          <h3>Edit Claim</h3>
          <label className="kb-field kb-field--full">Canonical Text<textarea rows={3} value={draft.canonical_text} onChange={(e) => setDraft({ ...draft, canonical_text: e.target.value })} /></label>
          <label className="kb-field kb-field--full">Short Wording<textarea rows={2} value={draft.short_text} onChange={(e) => setDraft({ ...draft, short_text: e.target.value })} /></label>
          <label className="kb-field kb-field--full">Long Wording<textarea rows={4} value={draft.long_text} onChange={(e) => setDraft({ ...draft, long_text: e.target.value })} /></label>
          <label className="kb-field kb-field--full">Restrictions<input value={draft.restrictions} onChange={(e) => setDraft({ ...draft, restrictions: e.target.value })} /></label>
          <div className="button-row">
            <button className="primary-button" type="button" onClick={saveEdit} disabled={busy}>Save</button>
            <button className="secondary-button" type="button" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <div className="detail-grid">
            <Row label="Status"><StatusBadge status={claim.status} /></Row>
            <Row label="Category">{claim.category || "—"}</Row>
            <Row label="Canonical Text">{claim.canonical_text}</Row>
            <Row label="Short Wording">{claim.short_text || "—"}</Row>
            <Row label="Long Wording">{claim.long_text || "—"}</Row>
            <Row label="Applicable States">{(claim.applicable_states || []).join(", ") || "All"}</Row>
            <Row label="Service Scope">{(claim.service_scope || []).join(", ") || "All"}</Row>
            <Row label="Industry Scope">{(claim.industry_scope || []).join(", ") || "All"}</Row>
            <Row label="Confidence">{claim.confidence || "—"}</Row>
            <Row label="Restrictions">{claim.restrictions || "—"}</Row>
            <Row label="Prohibited Use">{claim.prohibited_use_notes || "—"}</Row>
            <Row label="Source Document">{claim.source_document_id ? (
              <button className="link-button" type="button" onClick={() => onNavigate("kbDocumentDetail", { id: claim.source_document_id })}>
                Document {claim.source_document_id}{claim.source_page ? ` · p.${claim.source_page}` : ""}
              </button>
            ) : "—"}</Row>
            <Row label="Supporting Excerpt">{claim.supporting_excerpt || "—"}</Row>
            <Row label="Effective">{formatDate(claim.effective_date) || "—"}</Row>
            <Row label="Expiration">{formatDate(claim.expiration_date) || "—"}</Row>
            <Row label="Version">{claim.version}</Row>
            <Row label="Superseded By">{claim.superseded_by_id || "—"}</Row>
          </div>

          <h2>Evidence Sources ({detail.sources.length})</h2>
          {!detail.sources.length ? (
            <p className="muted-text">No evidence records.</p>
          ) : (
            detail.sources.map((s) => (
              <div className="kb-citation" key={s.id}>
                Document {s.document_id}{s.page_number ? ` · page ${s.page_number}` : ""}{s.section ? ` · ${s.section}` : ""}
                {s.excerpt ? <div className="muted-text">{s.excerpt}</div> : null}
              </div>
            ))
          )}

          <h2>Version History ({detail.versions.length})</h2>
          <table className="data-table">
            <thead><tr><th>Version</th><th>Change</th><th>When</th><th></th></tr></thead>
            <tbody>
              {detail.versions.map((v) => (
                <tr key={v.id}>
                  <td>{v.version}</td>
                  <td>{v.change_note || ""}</td>
                  <td>{formatDate(v.created_at)}</td>
                  <td><button className="link-button" type="button" onClick={() => restore(v.id)}>Restore</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </KbPage>
  );
}

function Row({ label, children }) {
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}
