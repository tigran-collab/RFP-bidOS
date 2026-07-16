import { useState } from "react";

import { detectKbConflicts, dismissKbConflict, getKbConflicts, resolveKbConflict } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function ConflictQueue({ onNavigate }) {
  const meta = useKbMeta();
  const [status, setStatus] = useState("Open");
  const { data, loading, error, reload } = useAsync(() => getKbConflicts({ status }), [status]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function detect() {
    setBusy(true);
    setMsg("");
    try {
      const r = await detectKbConflicts();
      setMsg(`Detected ${r.detected} new conflict(s).`);
      reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resolve(conflict, resolution, authoritativeClaimId) {
    try {
      const explanation = window.prompt("Explanation (optional):") || "";
      await resolveKbConflict(conflict.id, {
        resolution,
        authoritative_claim_id: authoritativeClaimId,
        explanation,
      });
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function dismiss(conflict) {
    try {
      await dismissKbConflict(conflict.id, window.prompt("Dismissal note:") || "");
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const conflicts = data || [];

  return (
    <KbPage
      current="kbConflicts"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Conflict Queue"
      actions={
        <button className="primary-button" type="button" onClick={detect} disabled={busy}>
          {busy ? "Detecting..." : "Detect Conflicts"}
        </button>
      }
    >
      {msg ? <p className="notice-text">{msg}</p> : null}
      <div className="kb-filters">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {(meta?.conflict_statuses || ["Open", "Resolved", "Dismissed"]).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>

      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : !conflicts.length ? (
        <p className="muted-text">No {status.toLowerCase()} conflicts.</p>
      ) : (
        conflicts.map((c) => (
          <div className="kb-card" key={c.id}>
            <h3>{c.detail || c.conflict_type}</h3>
            <p className="muted-text">Type: {c.conflict_type} · created {formatDate(c.created_at)}</p>
            <div className="kb-two-col">
              <div className="kb-citation">
                <strong>Claim A</strong>{" "}
                <button className="link-button" type="button" onClick={() => onNavigate("kbClaimDetail", { id: c.claim_a_id })}>#{c.claim_a_id}</button>
                <div>Value: <strong>{c.value_a}</strong></div>
              </div>
              <div className="kb-citation">
                <strong>Claim B</strong>{" "}
                <button className="link-button" type="button" onClick={() => onNavigate("kbClaimDetail", { id: c.claim_b_id })}>#{c.claim_b_id}</button>
                <div>Value: <strong>{c.value_b}</strong></div>
              </div>
            </div>
            {c.status === "Open" ? (
              <div className="kb-inline-actions" style={{ marginTop: "0.75rem" }}>
                <button className="secondary-button" type="button" onClick={() => resolve(c, "Superseded", c.claim_a_id)}>A supersedes B</button>
                <button className="secondary-button" type="button" onClick={() => resolve(c, "Superseded", c.claim_b_id)}>B supersedes A</button>
                <button className="secondary-button" type="button" onClick={() => resolve(c, "Authoritative Selected", c.claim_a_id)}>A authoritative</button>
                <button className="secondary-button" type="button" onClick={() => resolve(c, "Merged", c.claim_a_id)}>Merge</button>
                <button className="secondary-button" type="button" onClick={() => resolve(c, "Restricted", c.claim_b_id)}>Restrict B</button>
                <button className="secondary-button" type="button" onClick={() => dismiss(c)}>Dismiss</button>
              </div>
            ) : (
              <p className="muted-text">Resolved: {c.resolution || "—"} {c.explanation ? `· ${c.explanation}` : ""}</p>
            )}
          </div>
        ))
      )}
    </KbPage>
  );
}
