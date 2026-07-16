import { useState } from "react";

import {
  archiveKbDocument,
  getKbDocument,
  kbDocumentFileUrl,
  processKbDocument,
} from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, formatDate } from "./KbShared.jsx";

export default function DocumentDetail({ params, onNavigate }) {
  const id = params?.id;
  const { data, loading, error, reload } = useAsync(() => getKbDocument(id), [id]);
  const [busy, setBusy] = useState("");

  async function run(action) {
    setBusy(action);
    try {
      if (action === "process") await processKbDocument(id);
      if (action === "archive") await archiveKbDocument(id, true);
      reload();
    } catch (err) {
      alert(err.message);
    } finally {
      setBusy("");
    }
  }

  const doc = data?.document;
  const chunks = data?.chunks || [];

  return (
    <KbPage
      current="kbDocumentDetail"
      onNavigate={onNavigate}
      onUserChange={reload}
      title={doc ? doc.title : "Document"}
      actions={
        <>
          <button className="secondary-button" type="button" onClick={() => onNavigate("kbDocuments")}>
            ← Vault
          </button>
          {doc ? (
            <>
              <a className="secondary-button button-link" href={kbDocumentFileUrl(id)} target="_blank" rel="noreferrer">
                Open Original
              </a>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => run("process")}>
                {busy === "process" ? "Processing..." : "Reprocess"}
              </button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => run("archive")}>
                Archive
              </button>
            </>
          ) : null}
        </>
      }
    >
      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading || !doc ? (
        <p>Loading...</p>
      ) : (
        <>
          <div className="detail-grid">
            <Row label="Status"><StatusBadge status={doc.processing_status} /></Row>
            {doc.processing_error ? <Row label="Error"><span className="error-text">{doc.processing_error}</span></Row> : null}
            <Row label="Type">{doc.doc_type || "—"}</Row>
            <Row label="Category">{doc.category || "—"}</Row>
            <Row label="File">{doc.filename} ({doc.file_type}, {Math.round((doc.size_bytes || 0) / 1024)} KB)</Row>
            <Row label="State">{doc.applicable_state || "—"}</Row>
            <Row label="Industry">{doc.applicable_industry || "—"}</Row>
            <Row label="Service Type">{doc.service_type || "—"}</Row>
            <Row label="Pages / Chunks">{doc.page_count ?? "—"} / {doc.chunk_count ?? "—"}</Row>
            <Row label="Sheets">{(doc.sheet_names || []).join(", ") || "—"}</Row>
            <Row label="Effective">{formatDate(doc.effective_date) || "—"}</Row>
            <Row label="Expiration">{formatDate(doc.expiration_date) || "—"}</Row>
            <Row label="Uploaded">{formatDate(doc.uploaded_at)}</Row>
            <Row label="Tags">{(doc.tags || []).join(", ") || "—"}</Row>
          </div>

          {doc.injection_flags?.length ? (
            <>
              <h2>⚠ Prompt-Injection Flags ({doc.injection_flags.length})</h2>
              <ul className="kb-warnings">
                {doc.injection_flags.map((f, i) => (
                  <li key={i} className="kb-warning kb-warning--warn">
                    <strong>{f.pattern}</strong>{f.page ? ` (page ${f.page})` : ""}: {f.snippet}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          <h2>Extracted Text ({chunks.length} chunks)</h2>
          {!chunks.length ? (
            <p className="muted-text">No extracted text. Reprocess the document.</p>
          ) : (
            chunks.map((c) => (
              <div className="kb-card" key={c.id}>
                <p className="muted-text">
                  {c.page_number ? `Page ${c.page_number}` : ""}
                  {c.sheet_name ? `Sheet ${c.sheet_name}` : ""}
                  {c.cell_range ? ` (${c.cell_range})` : ""}
                  {c.section ? ` · ${c.section}` : ""}
                </p>
                <div className="kb-response-text">{c.text}</div>
              </div>
            ))
          )}
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
