import { useRef, useState } from "react";

import {
  getKbDocuments,
  getKbDriveFiles,
  getKbDriveStatus,
  getKbEntities,
  importKbDriveFiles,
  uploadKbDocuments,
} from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function DocumentVault({ onNavigate }) {
  const meta = useKbMeta();
  const [filters, setFilters] = useState({ archived: false });
  const { data, loading, error, reload } = useAsync(
    () => getKbDocuments(filters),
    [JSON.stringify(filters)],
  );
  const entities = useAsync(() => getKbEntities(), []);

  const fileInput = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadMeta, setUploadMeta] = useState({});
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");

  const drive = useAsync(() => getKbDriveStatus(), []);
  const [driveFiles, setDriveFiles] = useState(null);
  const [driveSel, setDriveSel] = useState({});
  const [driveMsg, setDriveMsg] = useState("");
  const [driveBusy, setDriveBusy] = useState(false);

  async function loadDriveFiles() {
    setDriveBusy(true);
    setDriveMsg("");
    try {
      const res = await getKbDriveFiles();
      if (res.error) setDriveMsg(res.error);
      setDriveFiles(res.files || []);
    } catch (err) {
      setDriveMsg(err.message);
    } finally {
      setDriveBusy(false);
    }
  }

  async function importDrive() {
    const ids = Object.keys(driveSel).filter((k) => driveSel[k]);
    if (!ids.length) return;
    setDriveBusy(true);
    setDriveMsg("");
    try {
      const res = await importKbDriveFiles(ids, uploadMeta.company_entity_id || undefined);
      setDriveMsg(
        `Imported ${res.imported || 0} file(s); processing started.` +
          (res.errors?.length ? ` Errors: ${res.errors.join("; ")}` : ""),
      );
      setDriveSel({});
      reload();
    } catch (err) {
      setDriveMsg(err.message);
    } finally {
      setDriveBusy(false);
    }
  }

  async function doUpload(fileList) {
    if (!fileList || !fileList.length) return;
    setUploading(true);
    setUploadMsg("");
    try {
      const form = new FormData();
      Array.from(fileList).forEach((f) => form.append("files", f));
      Object.entries(uploadMeta).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") form.append(k, v);
      });
      form.append("process", "true");
      const result = await uploadKbDocuments(form);
      const n = result.documents?.length || 0;
      setUploadMsg(
        `Uploaded ${n} document(s); processing started.` +
          (result.errors?.length ? ` Errors: ${result.errors.join("; ")}` : ""),
      );
      reload();
    } catch (err) {
      setUploadMsg(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const documents = data || [];

  return (
    <KbPage
      current="kbDocuments"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Source Document Vault"
    >
      <div
        className={dragOver ? "kb-dropzone kb-dropzone--over" : "kb-dropzone"}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          doUpload(e.dataTransfer.files);
        }}
        onClick={() => fileInput.current?.click()}
      >
        <input
          ref={fileInput}
          type="file"
          multiple
          style={{ display: "none" }}
          onChange={(e) => doUpload(e.target.files)}
        />
        {uploading ? "Uploading..." : "Drag & drop files here, or click to select. (PDF, DOCX, XLSX, CSV, TXT, images)"}
      </div>

      <div className="kb-form-grid" style={{ marginTop: "1rem" }}>
        <label className="kb-field">
          Company Entity
          <select
            value={uploadMeta.company_entity_id || ""}
            onChange={(e) => setUploadMeta({ ...uploadMeta, company_entity_id: e.target.value })}
          >
            <option value="">—</option>
            {(entities.data || []).map((ent) => (
              <option key={ent.id} value={ent.id}>{ent.name}</option>
            ))}
          </select>
        </label>
        <label className="kb-field">
          Document Type
          <select value={uploadMeta.doc_type || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, doc_type: e.target.value })}>
            <option value="">—</option>
            {(meta?.document_types || []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="kb-field">
          Category
          <select value={uploadMeta.category || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, category: e.target.value })}>
            <option value="">—</option>
            {(meta?.claim_categories || []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="kb-field">
          State
          <select value={uploadMeta.applicable_state || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, applicable_state: e.target.value })}>
            <option value="">—</option>
            {(meta?.states || []).map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="kb-field">
          Expiration Date
          <input type="date" value={uploadMeta.expiration_date || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, expiration_date: e.target.value })} />
        </label>
      </div>
      {uploadMsg ? <p className="notice-text">{uploadMsg}</p> : null}

      {drive.data?.configured ? (
        <div className="kb-card">
          <div className="kb-page-head" style={{ marginBottom: "0.5rem" }}>
            <h3 style={{ margin: 0 }}>Import from Google Drive</h3>
            <button className="secondary-button" type="button" onClick={loadDriveFiles} disabled={driveBusy}>
              {driveBusy ? "Loading..." : driveFiles ? "Refresh" : "Browse Drive"}
            </button>
          </div>
          {driveMsg ? <p className="notice-text">{driveMsg}</p> : null}
          {driveFiles && driveFiles.length ? (
            <>
              <ul className="kb-drive-list">
                {driveFiles.map((f) => (
                  <li key={f.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={!!driveSel[f.id]}
                        onChange={(e) => setDriveSel({ ...driveSel, [f.id]: e.target.checked })}
                      />
                      {" "}{f.name}
                      <span className="muted-text"> — {(f.mimeType || "").replace("application/vnd.google-apps.", "Google ")}</span>
                    </label>
                  </li>
                ))}
              </ul>
              <button
                className="primary-button"
                type="button"
                onClick={importDrive}
                disabled={driveBusy || !Object.values(driveSel).some(Boolean)}
              >
                Import Selected
              </button>
            </>
          ) : driveFiles ? (
            <p className="muted-text">No files found in the configured Drive folder.</p>
          ) : null}
        </div>
      ) : null}

      <div className="kb-filters">
        <label>
          Status
          <select value={filters.processing_status || ""} onChange={(e) => setFilters({ ...filters, processing_status: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.doc_statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Category
          <select value={filters.category || ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.claim_categories || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Expiration
          <select value={filters.expiration || ""} onChange={(e) => setFilters({ ...filters, expiration: e.target.value || undefined })}>
            <option value="">All</option>
            <option value="expired">Expired</option>
            <option value="active">Active</option>
          </select>
        </label>
        <label>
          Archived
          <select value={String(filters.archived)} onChange={(e) => setFilters({ ...filters, archived: e.target.value === "true" })}>
            <option value="false">No</option>
            <option value="true">Yes</option>
          </select>
        </label>
      </div>

      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : !documents.length ? (
        <p className="muted-text">No documents yet. Upload some above.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Title</th><th>Type</th><th>Category</th><th>Status</th>
              <th>Pages</th><th>Expiration</th><th>Uploaded</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((d) => (
              <tr key={d.id}>
                <td>
                  <button className="link-button" type="button" onClick={() => onNavigate("kbDocumentDetail", { id: d.id })}>
                    {d.title}
                  </button>
                </td>
                <td>{d.doc_type || ""}</td>
                <td>{d.category || ""}</td>
                <td><StatusBadge status={d.processing_status} /></td>
                <td>{d.page_count ?? ""}</td>
                <td>{formatDate(d.expiration_date)}</td>
                <td>{formatDate(d.uploaded_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </KbPage>
  );
}
