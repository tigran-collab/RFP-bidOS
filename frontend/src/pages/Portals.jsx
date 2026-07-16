import { Fragment, useEffect, useRef, useState } from "react";

import LoadError from "../components/LoadError.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import {
  addPortal,
  deleteSourceCredentials,
  getLoginStatus,
  getPortalTemplates,
  getSources,
  scrapeSource,
  setSourceCredentials,
  setSourceEnabled,
  startPortalLogin,
  updateSource,
} from "../api.js";

const loadError = "Failed to load portals. Is the backend running?";

// Derive a human-friendly status label for a credential source, folding in the
// latest login-status poll result when we have one.
function statusLabel(source, login) {
  if (login?.state === "success") return "Session active";
  if (login?.state === "expired") return "Session expired";
  if (login?.state === "failed") return "Login failed";
  if (login?.state === "launching" || login?.state === "awaiting_user") {
    return "Logging in";
  }
  // A saved browser session is what downloads actually run on — report it
  // even when the keychain credentials need (re-)saving.
  if (login?.has_session_profile) return "Session saved";
  const auth = login?.auth_status?.auth_status || source.auth_status;
  if (auth === "Configured") return "Ready";
  return "Needs credentials";
}

function formatScrapeResult(result) {
  if (!result) return "";
  if (result.errors?.length) {
    return `${result.errors.length} error(s): ${result.errors.join("; ")}`;
  }
  return (
    `${result.records_found ?? 0} kept, ` +
    `${result.created_count ?? 0} created, ` +
    `${result.updated_count ?? 0} updated, ` +
    `${result.skipped_duplicates ?? 0} duplicates skipped`
  );
}

function prettyConfig(value) {
  if (!value) return "";
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export default function Portals() {
  const [sources, setSources] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadErr, setLoadErr] = useState("");
  const [message, setMessage] = useState("");

  // Add-a-portal form state.
  const [newTemplate, setNewTemplate] = useState("");
  const [newName, setNewName] = useState("");
  const [newLoginUrl, setNewLoginUrl] = useState("");
  const [newListUrl, setNewListUrl] = useState("");
  const [adding, setAdding] = useState(false);

  // Per-source expand + credential inputs + progress.
  const [expanded, setExpanded] = useState(null);
  const [creds, setCreds] = useState({}); // {id: {username, password}}
  // {id: {saving|login|scrape|deleting|toggle|config: true}} — per-action flags so
  // concurrent operations on one row (e.g. a scrape and a config save) don't
  // clobber each other's busy state.
  const [busy, setBusy] = useState({});
  const [loginStatus, setLoginStatus] = useState({}); // {id: statusObj}
  const [rowMessage, setRowMessage] = useState({}); // {id: string}
  const [configEdits, setConfigEdits] = useState({}); // {id: {login_url, base_url, config_json}}

  const pollers = useRef({});

  async function loadAll() {
    try {
      setLoading(true);
      const [loadedSources, loadedTemplates] = await Promise.all([
        getSources(),
        getPortalTemplates(),
      ]);
      const credentialSources = (loadedSources || []).filter(
        (s) => s.requires_credentials,
      );
      setSources(credentialSources);
      setTemplates(loadedTemplates || []);
      setLoadErr("");
      // Fill in live status (saved session, keychain state) per portal in the
      // background so labels reflect reality on load, not the stale DB column.
      credentialSources.forEach((source) => {
        refreshLoginStatus(source.id);
      });
    } catch (err) {
      setLoadErr(err.message || loadError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // Stop any polling loops on unmount.
    return () => {
      Object.values(pollers.current).forEach((id) => clearInterval(id));
      pollers.current = {};
    };
  }, []);

  function setRowBusy(id, action, active) {
    setBusy((current) => {
      const entry = { ...(current[id] || {}) };
      if (active) entry[action] = true;
      else delete entry[action];
      return { ...current, [id]: entry };
    });
  }

  function updateCred(id, field, value) {
    setCreds((current) => ({
      ...current,
      [id]: { ...(current[id] || {}), [field]: value },
    }));
  }

  function updateConfig(id, field, value) {
    setConfigEdits((current) => ({
      ...current,
      [id]: { ...(current[id] || {}), [field]: value },
    }));
  }

  function configValue(source, field) {
    const draft = configEdits[source.id] || {};
    if (draft[field] !== undefined) return draft[field];
    if (field === "config_json") return prettyConfig(source.config_json);
    return source[field] || "";
  }

  async function refreshLoginStatus(id) {
    try {
      const status = await getLoginStatus(id);
      setLoginStatus((current) => ({ ...current, [id]: status }));
      return status;
    } catch {
      return null;
    }
  }

  async function handleAddPortal(event) {
    event.preventDefault();
    if (!newName.trim()) {
      setError("Enter a name for the portal.");
      return;
    }
    try {
      setAdding(true);
      const created = await addPortal({
        template: newTemplate || undefined,
        name: newName.trim(),
        // Without a template the backend requires an explicit source type; every
        // assisted-login portal uses the authenticated_browser adapter.
        source_type: newTemplate ? undefined : "authenticated_browser",
        login_url: newLoginUrl.trim() || undefined,
        list_url: newListUrl.trim() || undefined,
      });
      setNewName("");
      setNewTemplate("");
      setNewLoginUrl("");
      setNewListUrl("");
      await loadAll();
      setExpanded(created.id);
      setMessage(`Added portal "${created.name}". Enter credentials to continue.`);
      setError("");
    } catch (exc) {
      setError(exc.message || "Failed to add portal.");
    } finally {
      setAdding(false);
    }
  }

  async function handleSaveCredentials(source) {
    const entry = creds[source.id] || {};
    const username = entry.username || source.credential_username || "";
    if (!username || !entry.password) {
      setRowMessage((c) => ({ ...c, [source.id]: "Enter a username and password." }));
      return;
    }
    try {
      setRowBusy(source.id, "saving", true);
      await setSourceCredentials(source.id, {
        username,
        password: entry.password,
      });
      // Clear the password field immediately; never keep it in state.
      updateCred(source.id, "password", "");
      setRowMessage((c) => ({ ...c, [source.id]: "Credentials saved to the OS keychain." }));
      await refreshLoginStatus(source.id);
      await loadAll();
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Failed to save credentials." }));
    } finally {
      setRowBusy(source.id, "saving", false);
    }
  }

  async function handleDeleteCredentials(source) {
    try {
      setRowBusy(source.id, "deleting", true);
      await deleteSourceCredentials(source.id);
      updateCred(source.id, "username", "");
      updateCred(source.id, "password", "");
      setRowMessage((c) => ({ ...c, [source.id]: "Credentials removed." }));
      await refreshLoginStatus(source.id);
      await loadAll();
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Failed to remove credentials." }));
    } finally {
      setRowBusy(source.id, "deleting", false);
    }
  }

  function stopPolling(id) {
    if (pollers.current[id]) {
      clearInterval(pollers.current[id]);
      delete pollers.current[id];
    }
  }

  async function handleLogin(source) {
    try {
      setRowBusy(source.id, "login", true);
      setRowMessage((c) => ({
        ...c,
        [source.id]: "Opening browser — complete the login in the window that opened…",
      }));
      const status = await startPortalLogin(source.id);
      setLoginStatus((current) => ({ ...current, [source.id]: status }));
      if (status.state === "failed") {
        setRowMessage((c) => ({ ...c, [source.id]: status.message }));
        setRowBusy(source.id, "login", false);
        return;
      }
      // Poll login-status every ~2s until it settles (or 5 minutes pass).
      stopPolling(source.id);
      const pollDeadline = Date.now() + 5 * 60 * 1000;
      pollers.current[source.id] = setInterval(async () => {
        if (Date.now() > pollDeadline) {
          stopPolling(source.id);
          setRowBusy(source.id, "login", false);
          setRowMessage((c) => ({
            ...c,
            [source.id]:
              "Login timed out. Close the browser window and try again.",
          }));
          return;
        }
        const latest = await refreshLoginStatus(source.id);
        if (!latest) return;
        if (["success", "expired", "failed"].includes(latest.state)) {
          stopPolling(source.id);
          setRowBusy(source.id, "login", false);
          if (latest.state === "success") {
            setRowMessage((c) => ({ ...c, [source.id]: "✓ Session active." }));
            loadAll();
          } else {
            setRowMessage((c) => ({ ...c, [source.id]: latest.message }));
          }
        } else {
          setRowMessage((c) => ({
            ...c,
            [source.id]: "Opening browser — complete the login in the window that opened…",
          }));
        }
      }, 2000);
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Failed to start login." }));
      setRowBusy(source.id, "login", false);
    }
  }

  async function handleToggleEnabled(source) {
    try {
      setRowBusy(source.id, "toggle", true);
      await setSourceEnabled(source.id, !source.enabled);
      await loadAll();
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Failed to update." }));
    } finally {
      setRowBusy(source.id, "toggle", false);
    }
  }

  async function handleSaveConfig(source) {
    const loginUrl = configValue(source, "login_url").trim();
    const baseUrl = configValue(source, "base_url").trim();
    const rawConfig = configValue(source, "config_json").trim();
    let normalizedConfig = null;
    if (rawConfig) {
      try {
        normalizedConfig = JSON.stringify(JSON.parse(rawConfig), null, 2);
      } catch {
        setRowMessage((c) => ({ ...c, [source.id]: "Config JSON is not valid." }));
        return;
      }
    }
    // Snapshot the draft as it was sent so keystrokes typed while the PATCH is
    // in flight survive: afterwards we only drop draft fields that still match
    // this snapshot.
    const sentDraft = { ...(configEdits[source.id] || {}) };
    try {
      setRowBusy(source.id, "config", true);
      await updateSource(source.id, {
        login_url: loginUrl || null,
        base_url: baseUrl || null,
        config_json: normalizedConfig,
      });
      // Refresh sources first so clearing the draft never reveals stale values.
      await loadAll();
      setConfigEdits((current) => {
        const entry = current[source.id];
        if (!entry) return current;
        const remaining = {};
        for (const [field, value] of Object.entries(entry)) {
          if (sentDraft[field] !== value) remaining[field] = value;
        }
        const next = { ...current };
        if (Object.keys(remaining).length) next[source.id] = remaining;
        else delete next[source.id];
        return next;
      });
      setRowMessage((c) => ({ ...c, [source.id]: "Portal configuration saved." }));
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Failed to save configuration." }));
    } finally {
      setRowBusy(source.id, "config", false);
    }
  }

  async function handleScrape(source) {
    try {
      setRowBusy(source.id, "scrape", true);
      const result = await scrapeSource(source.id);
      setRowMessage((c) => ({ ...c, [source.id]: formatScrapeResult(result) }));
    } catch (exc) {
      setRowMessage((c) => ({ ...c, [source.id]: exc.message || "Scrape failed." }));
    } finally {
      setRowBusy(source.id, "scrape", false);
    }
  }

  if (loading) {
    return <p>Loading portals…</p>;
  }

  return (
    <section>
      <h1>Portals</h1>
      <p className="muted-text">
        Manage authenticated procurement portals here — add a portal, store its
        login in the OS keychain, complete a one-time assisted login in a visible
        browser, enable it, and scrape. Passwords are never stored in the app
        database and are never shown back to you.
      </p>

      <div className="edit-panel">
        <h2>Add a portal</h2>
        <form className="portal-add-form" onSubmit={handleAddPortal}>
          <label className="form-field">
            Template
            <select
              value={newTemplate}
              onChange={(event) => setNewTemplate(event.target.value)}
            >
              <option value="">Generic (no template)</option>
              {templates.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.display_name} [{t.source_type}]
                </option>
              ))}
            </select>
          </label>
          <label className="form-field">
            Name
            <input
              type="text"
              value={newName}
              placeholder="e.g. City of Example PlanetBids"
              onChange={(event) => setNewName(event.target.value)}
            />
          </label>
          <label className="form-field">
            Login URL
            <input
              type="url"
              value={newLoginUrl}
              placeholder="https://portal.example.gov/login"
              onChange={(event) => setNewLoginUrl(event.target.value)}
            />
          </label>
          <label className="form-field">
            List URL
            <input
              type="url"
              value={newListUrl}
              placeholder="https://portal.example.gov/bids"
              onChange={(event) => setNewListUrl(event.target.value)}
            />
          </label>
          <button className="primary-button" type="submit" disabled={adding}>
            {adding ? "Adding…" : "Add portal"}
          </button>
        </form>
      </div>

      {loadErr ? <LoadError message={loadErr} onRetry={loadAll} /> : null}
      {message ? (
        <p role="status" aria-live="polite">
          {message}
        </p>
      ) : null}
      {error ? (
        <p className="error-text" role="status" aria-live="polite">
          {error}
        </p>
      ) : null}

      {!sources.length ? (
        <p className="muted-text">
          No authenticated portals yet. Add one above to get started.
        </p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Status</th>
              <th>Enabled</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => {
              const login = loginStatus[source.id];
              const rowBusy = busy[source.id] || {};
              const isOpen = expanded === source.id;
              const entry = creds[source.id] || {};
              return (
                <Fragment key={source.id}>
                  <tr>
                    <td>
                      <strong>{source.name}</strong>
                      {source.credential_username ? (
                        <div className="muted-text">{source.credential_username}</div>
                      ) : null}
                    </td>
                    <td>
                      {source.portal_type || source.source_type}
                    </td>
                    <td>
                      <StatusBadge status={statusLabel(source, login)} />
                    </td>
                    <td>
                      <label className="portal-toggle">
                        <input
                          type="checkbox"
                          checked={Boolean(source.enabled)}
                          disabled={Boolean(rowBusy.toggle)}
                          onChange={() => handleToggleEnabled(source)}
                        />
                        {source.enabled ? "On" : "Off"}
                      </label>
                    </td>
                    <td>
                      <div className="button-row">
                        <button
                          className="secondary-button"
                          type="button"
                          onClick={() =>
                            setExpanded(isOpen ? null : source.id)
                          }
                        >
                          {isOpen ? "Close" : "Manage"}
                        </button>
                        <button
                          className="primary-button"
                          type="button"
                          disabled={!source.enabled || rowBusy.scrape}
                          onClick={() => handleScrape(source)}
                        >
                          {rowBusy.scrape ? "Scraping…" : "Scrape now"}
                        </button>
                      </div>
                    </td>
                  </tr>
                  {isOpen ? (
                    <tr>
                      <td colSpan={5}>
                        <div className="edit-panel portal-manage-panel">
                          <div className="portal-cred-fields">
                            <label className="form-field">
                              Username
                              <input
                                type="text"
                                autoComplete="off"
                                value={entry.username ?? source.credential_username ?? ""}
                                placeholder="Portal login username"
                                onChange={(event) =>
                                  updateCred(source.id, "username", event.target.value)
                                }
                              />
                            </label>
                            <label className="form-field">
                              Password
                              <input
                                type="password"
                                autoComplete="new-password"
                                value={entry.password ?? ""}
                                placeholder="Never stored in the app database"
                                onChange={(event) =>
                                  updateCred(source.id, "password", event.target.value)
                                }
                              />
                            </label>
                          </div>
                          <div className="button-row">
                            <button
                              className="secondary-button"
                              type="button"
                              disabled={Boolean(rowBusy.saving)}
                              onClick={() => handleSaveCredentials(source)}
                            >
                              {rowBusy.saving ? "Saving…" : "Save credentials"}
                            </button>
                            <button
                              className="primary-button"
                              type="button"
                              disabled={Boolean(rowBusy.login)}
                              onClick={() => handleLogin(source)}
                            >
                              {rowBusy.login ? "Logging in…" : "Log in"}
                            </button>
                            {source.credential_username ? (
                              <button
                                className="secondary-button"
                                type="button"
                                disabled={Boolean(rowBusy.deleting)}
                                onClick={() => handleDeleteCredentials(source)}
                              >
                                {rowBusy.deleting ? "Removing…" : "Remove credentials"}
                              </button>
                            ) : null}
                          </div>
                          <div className="portal-config-fields">
                            <label className="form-field">
                              Login URL
                              <input
                                type="url"
                                value={configValue(source, "login_url")}
                                placeholder="Portal login URL"
                                onChange={(event) =>
                                  updateConfig(source.id, "login_url", event.target.value)
                                }
                              />
                            </label>
                            <label className="form-field">
                              Base URL
                              <input
                                type="url"
                                value={configValue(source, "base_url")}
                                placeholder="Portal base or list URL"
                                onChange={(event) =>
                                  updateConfig(source.id, "base_url", event.target.value)
                                }
                              />
                            </label>
                            <label className="form-field portal-config-json">
                              Config JSON
                              <textarea
                                rows={10}
                                value={configValue(source, "config_json")}
                                placeholder='{"list_url": "https://portal.example.gov/bids"}'
                                onChange={(event) =>
                                  updateConfig(source.id, "config_json", event.target.value)
                                }
                              />
                            </label>
                          </div>
                          <div className="button-row">
                            <button
                              className="secondary-button"
                              type="button"
                              disabled={Boolean(rowBusy.config)}
                              onClick={() => handleSaveConfig(source)}
                            >
                              {rowBusy.config ? "Saving..." : "Save portal config"}
                            </button>
                          </div>
                          {rowMessage[source.id] ? (
                            <p className="muted-text notice-text">{rowMessage[source.id]}</p>
                          ) : null}
                          {login?.auth_status?.missing_fields?.length ? (
                            <p className="muted-text">
                              {login.auth_status.missing_fields.join("; ")}
                            </p>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
