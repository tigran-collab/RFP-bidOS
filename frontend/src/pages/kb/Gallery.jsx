import { useRef, useState } from "react";

import {
  archiveKbGalleryAsset,
  deleteKbGalleryAsset,
  getKbEntities,
  getKbGallery,
  kbGalleryFileUrl,
  updateKbGalleryAsset,
  uploadKbGallery,
} from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

function formatBytes(n) {
  if (!n) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export default function Gallery({ onNavigate }) {
  const meta = useKbMeta();
  const [filters, setFilters] = useState({ archived: false });
  const { data, loading, error, reload } = useAsync(
    () => getKbGallery(filters),
    [JSON.stringify(filters)],
  );
  const entities = useAsync(() => getKbEntities(), []);

  const fileInput = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploadMeta, setUploadMeta] = useState({});
  const [uploading, setUploading] = useState(false);
  const [msg, setMsg] = useState("");
  const [selected, setSelected] = useState(null);

  async function doUpload(fileList) {
    if (!fileList || !fileList.length) return;
    setUploading(true);
    setMsg("");
    try {
      const form = new FormData();
      Array.from(fileList).forEach((f) => form.append("files", f));
      Object.entries(uploadMeta).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") form.append(k, v);
      });
      const result = await uploadKbGallery(form);
      const n = result.assets?.length || 0;
      setMsg(
        `Uploaded ${n} asset(s).` +
          (result.errors?.length ? ` Errors: ${result.errors.join("; ")}` : ""),
      );
      reload();
    } catch (err) {
      setMsg(err.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const assets = data || [];

  return (
    <KbPage
      current="kbGallery"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Media Gallery"
    >
      <p className="muted-text">
        Reusable visual assets — logos, certification badges, team and facility
        photos, diagrams — for use in proposals. Images only; originals are stored
        securely and served by id.
      </p>

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
          accept="image/*"
          style={{ display: "none" }}
          onChange={(e) => doUpload(e.target.files)}
        />
        {uploading
          ? "Uploading..."
          : "Drag & drop logos/images here, or click to select. (PNG, JPG, GIF, WEBP, SVG, BMP)"}
      </div>

      <div className="kb-form-grid" style={{ marginTop: "1rem" }}>
        <label className="kb-field">
          Category
          <select value={uploadMeta.category || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, category: e.target.value })}>
            <option value="">—</option>
            {(meta?.gallery_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="kb-field">
          Company Entity
          <select value={uploadMeta.company_entity_id || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, company_entity_id: e.target.value })}>
            <option value="">—</option>
            {(entities.data || []).map((ent) => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
          </select>
        </label>
        <label className="kb-field">
          Tags (comma-separated)
          <input value={uploadMeta.tags || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, tags: e.target.value })} />
        </label>
        <label className="kb-field">
          Expiration Date
          <input type="date" value={uploadMeta.expiration_date || ""} onChange={(e) => setUploadMeta({ ...uploadMeta, expiration_date: e.target.value })} />
        </label>
      </div>
      {msg ? <p className="notice-text">{msg}</p> : null}

      <div className="kb-filters">
        <label>
          Category
          <select value={filters.category || ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.gallery_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
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
      ) : !assets.length ? (
        <p className="muted-text">No assets yet. Upload logos or images above.</p>
      ) : (
        <div className="kb-gallery-grid">
          {assets.map((a) => (
            <button
              type="button"
              className="kb-gallery-card"
              key={a.id}
              onClick={() => setSelected(a)}
              title={a.title}
            >
              <div className="kb-gallery-thumb">
                <img src={kbGalleryFileUrl(a.id)} alt={a.alt_text || a.title} loading="lazy" />
                {a.expired ? <span className="kb-gallery-badge kb-gallery-badge--danger">Expired</span> : null}
              </div>
              <div className="kb-gallery-meta">
                <span className="kb-gallery-title">{a.title}</span>
                <span className="muted-text">{a.category || a.file_type?.toUpperCase()}</span>
              </div>
            </button>
          ))}
        </div>
      )}

      {selected ? (
        <AssetModal
          asset={selected}
          meta={meta}
          entities={entities.data || []}
          onClose={() => setSelected(null)}
          onChanged={() => {
            reload();
            setSelected(null);
          }}
        />
      ) : null}
    </KbPage>
  );
}

function AssetModal({ asset, meta, entities, onClose, onChanged }) {
  const [form, setForm] = useState({
    title: asset.title || "",
    category: asset.category || "",
    company_entity_id: asset.company_entity_id || "",
    description: asset.description || "",
    alt_text: asset.alt_text || "",
    tags: (asset.tags || []).join(", "),
    expiration_date: asset.expiration_date ? asset.expiration_date.slice(0, 10) : "",
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  function set(k, v) {
    setForm({ ...form, [k]: v });
  }

  async function save() {
    setBusy(true);
    setErr("");
    try {
      await updateKbGalleryAsset(asset.id, {
        title: form.title,
        category: form.category || null,
        company_entity_id: form.company_entity_id ? Number(form.company_entity_id) : null,
        description: form.description || null,
        alt_text: form.alt_text || null,
        tags: form.tags ? form.tags.split(",").map((t) => t.trim()).filter(Boolean) : [],
        expiration_date: form.expiration_date || null,
      });
      onChanged();
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    setBusy(true);
    try {
      await archiveKbGalleryAsset(asset.id, !asset.archived);
      onChanged();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete "${asset.title}"? This cannot be undone.`)) return;
    setBusy(true);
    try {
      await deleteKbGalleryAsset(asset.id);
      onChanged();
    } catch (e) {
      setErr(e.message);
      setBusy(false);
    }
  }

  return (
    <div className="kb-modal-overlay" onClick={onClose}>
      <div className="kb-modal" onClick={(e) => e.stopPropagation()}>
        <div className="kb-modal-head">
          <h2>{asset.title}</h2>
          <button className="secondary-button" type="button" onClick={onClose}>Close</button>
        </div>
        <div className="kb-modal-body">
          <div className="kb-modal-preview">
            <img src={kbGalleryFileUrl(asset.id)} alt={asset.alt_text || asset.title} />
            <p className="muted-text">
              {asset.file_type?.toUpperCase()}
              {asset.width ? ` · ${asset.width}×${asset.height}` : ""}
              {asset.size_bytes ? ` · ${formatBytes(asset.size_bytes)}` : ""}
              {asset.uploaded_at ? ` · uploaded ${formatDate(asset.uploaded_at)}` : ""}
            </p>
            <div className="button-row">
              <a className="secondary-button button-link" href={kbGalleryFileUrl(asset.id)} target="_blank" rel="noreferrer">Open / Download</a>
            </div>
          </div>
          <div className="kb-modal-form">
            {err ? <p className="error-text">{err}</p> : null}
            <label className="kb-field">Title<input value={form.title} onChange={(e) => set("title", e.target.value)} /></label>
            <label className="kb-field">Category
              <select value={form.category} onChange={(e) => set("category", e.target.value)}>
                <option value="">—</option>
                {(meta?.gallery_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="kb-field">Company Entity
              <select value={form.company_entity_id} onChange={(e) => set("company_entity_id", e.target.value)}>
                <option value="">—</option>
                {entities.map((ent) => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
              </select>
            </label>
            <label className="kb-field">Alt text<input value={form.alt_text} onChange={(e) => set("alt_text", e.target.value)} /></label>
            <label className="kb-field">Description<textarea rows={2} value={form.description} onChange={(e) => set("description", e.target.value)} /></label>
            <label className="kb-field">Tags (comma-separated)<input value={form.tags} onChange={(e) => set("tags", e.target.value)} /></label>
            <label className="kb-field">Expiration Date<input type="date" value={form.expiration_date} onChange={(e) => set("expiration_date", e.target.value)} /></label>
            <div className="button-row" style={{ marginTop: "0.5rem" }}>
              <button className="primary-button" type="button" onClick={save} disabled={busy}>Save</button>
              <button className="secondary-button" type="button" onClick={archive} disabled={busy}>
                {asset.archived ? "Unarchive" : "Archive"}
              </button>
              <button className="danger-button" type="button" onClick={remove} disabled={busy}>Delete</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
