import { useState } from "react";

import { createKbClaim, expireKbClaims, getKbClaims, getKbEntities } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

const EMPTY = { title: "", canonical_text: "", category: "", company_entity_id: "" };

export default function ClaimsRegistry({ onNavigate }) {
  const meta = useKbMeta();
  const [filters, setFilters] = useState({});
  const { data, loading, error, reload } = useAsync(
    () => getKbClaims(filters),
    [JSON.stringify(filters)],
  );
  const entities = useAsync(() => getKbEntities(), []);
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);
  const [msg, setMsg] = useState("");

  async function create() {
    setMsg("");
    try {
      const payload = { ...form };
      if (!payload.company_entity_id) delete payload.company_entity_id;
      const claim = await createKbClaim(payload);
      setForm(EMPTY);
      setShowForm(false);
      onNavigate("kbClaimDetail", { id: claim.id });
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function runExpire() {
    try {
      const r = await expireKbClaims();
      setMsg(`Expired ${r.expired} claim(s).`);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const claims = data || [];

  return (
    <KbPage
      current="kbClaims"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Claims Registry"
      actions={
        <>
          <button className="primary-button" type="button" onClick={() => setShowForm((s) => !s)}>
            {showForm ? "Cancel" : "New Claim"}
          </button>
          <button className="secondary-button" type="button" onClick={runExpire}>
            Run Expiration Sweep
          </button>
        </>
      }
    >
      {msg ? <p className="notice-text">{msg}</p> : null}

      {showForm ? (
        <div className="kb-card">
          <h3>New Claim</h3>
          <div className="kb-form-grid">
            <label className="kb-field kb-field--full">
              Title
              <input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </label>
            <label className="kb-field kb-field--full">
              Canonical Text
              <textarea rows={3} value={form.canonical_text} onChange={(e) => setForm({ ...form, canonical_text: e.target.value })} />
            </label>
            <label className="kb-field">
              Category
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                <option value="">—</option>
                {(meta?.claim_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label className="kb-field">
              Company Entity
              <select value={form.company_entity_id} onChange={(e) => setForm({ ...form, company_entity_id: e.target.value })}>
                <option value="">—</option>
                {(entities.data || []).map((ent) => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
              </select>
            </label>
          </div>
          <button className="primary-button" type="button" onClick={create} disabled={!form.title || !form.canonical_text}>
            Create Claim
          </button>
        </div>
      ) : null}

      <div className="kb-filters">
        <label>
          Status
          <select value={filters.status || ""} onChange={(e) => setFilters({ ...filters, status: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.claim_statuses || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Category
          <select value={filters.category || ""} onChange={(e) => setFilters({ ...filters, category: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.claim_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>
          State
          <select value={filters.state || ""} onChange={(e) => setFilters({ ...filters, state: e.target.value || undefined })}>
            <option value="">All</option>
            {(meta?.states || []).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : !claims.length ? (
        <p className="muted-text">No claims match.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr><th>Title</th><th>Category</th><th>Status</th><th>Confidence</th><th>Expiration</th><th>Updated</th></tr>
          </thead>
          <tbody>
            {claims.map((c) => (
              <tr key={c.id}>
                <td>
                  <button className="link-button" type="button" onClick={() => onNavigate("kbClaimDetail", { id: c.id })}>
                    {c.title}
                  </button>
                </td>
                <td>{c.category || ""}</td>
                <td><StatusBadge status={c.status} /></td>
                <td>{c.confidence || ""}</td>
                <td>{formatDate(c.expiration_date)}</td>
                <td>{formatDate(c.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </KbPage>
  );
}
