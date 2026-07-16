import { useCallback, useEffect, useState } from "react";

import { getKbMeta, getKbUsers, getKbUserId, setKbUserId } from "../../api.js";
import StatusBadge from "../../components/StatusBadge.jsx";

// KB sub-navigation tabs.
export const KB_TABS = [
  { key: "kbDashboard", label: "Dashboard" },
  { key: "kbDocuments", label: "Documents" },
  { key: "kbGallery", label: "Gallery" },
  { key: "kbClaims", label: "Claims" },
  { key: "kbAnswers", label: "Answers" },
  { key: "kbWorkspace", label: "Workspace" },
  { key: "kbResponses", label: "Responses" },
  { key: "kbConflicts", label: "Conflicts" },
  { key: "kbExpirations", label: "Expirations" },
  { key: "kbAdmin", label: "Admin" },
];

// Detail pages highlight their parent tab.
const PARENT_TAB = {
  kbDocumentDetail: "kbDocuments",
  kbClaimDetail: "kbClaims",
  kbAnswerEditor: "kbAnswers",
};

export function parentTab(page) {
  return PARENT_TAB[page] || page;
}

export function formatDate(value) {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

// Module-level meta cache (loaded once).
let metaPromise = null;

export function useKbMeta() {
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    if (!metaPromise) metaPromise = getKbMeta();
    let active = true;
    metaPromise.then((m) => active && setMeta(m)).catch(() => {});
    return () => {
      active = false;
    };
  }, []);
  return meta;
}

export function useAsync(loader, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const run = useCallback(async () => {
    setLoading(true);
    try {
      const result = await loader();
      setData(result);
      setError("");
    } catch (err) {
      setError(err.message || "Request failed");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    run();
  }, [run]);
  return { data, loading, error, reload: run, setData };
}

function KbUserSwitcher({ onUserChange }) {
  const [users, setUsers] = useState([]);
  const [current, setCurrent] = useState(getKbUserId() || "");
  useEffect(() => {
    getKbUsers()
      .then((list) => {
        setUsers(list);
        // Default the selector to the admin when nothing is chosen yet.
        if (!getKbUserId() && list.length) {
          const admin = list.find((u) => u.role === "administrator") || list[0];
          setKbUserId(admin.id);
          setCurrent(String(admin.id));
        }
      })
      .catch(() => {});
  }, []);

  function handleChange(event) {
    const value = event.target.value;
    setKbUserId(value || null);
    setCurrent(value);
    onUserChange && onUserChange();
  }

  return (
    <label className="kb-user-switcher">
      <span>Acting as</span>
      <select value={current} onChange={handleChange}>
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name} ({u.role.replace("_", " ")})
          </option>
        ))}
      </select>
    </label>
  );
}

export function KbSubnav({ current, onNavigate, onUserChange }) {
  const active = parentTab(current);
  return (
    <div className="kb-subnav">
      <div className="kb-subnav-tabs">
        {KB_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={active === tab.key ? "kb-tab kb-tab--active" : "kb-tab"}
            onClick={() => onNavigate(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <KbUserSwitcher onUserChange={onUserChange} />
    </div>
  );
}

const SEVERITY_LABEL = { high: "danger", medium: "warn", low: "info" };

export function Warnings({ warnings }) {
  if (!warnings || !warnings.length) {
    return <p className="muted-text">No warnings.</p>;
  }
  return (
    <ul className="kb-warnings">
      {warnings.map((w, i) => (
        <li key={i} className={`kb-warning kb-warning--${SEVERITY_LABEL[w.severity] || "info"}`}>
          <strong>{w.type.replace(/_/g, " ")}</strong>: {w.message}
        </li>
      ))}
    </ul>
  );
}

export function KbPage({ current, onNavigate, onUserChange, title, actions, children }) {
  return (
    <section>
      <KbSubnav current={current} onNavigate={onNavigate} onUserChange={onUserChange} />
      <div className="kb-page-head">
        <h1>{title}</h1>
        {actions ? <div className="page-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export { StatusBadge };
