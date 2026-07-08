import { useEffect, useState } from "react";

import LoadError from "../components/LoadError.jsx";
import StatusBadge from "../components/StatusBadge.jsx";
import {
  deleteNotionConfig,
  getNotionStatus,
  saveNotionConfig,
  syncNotion,
} from "../api.js";

const loadError = "Failed to load Notion status. Is the backend running?";

function connectionLabel(status) {
  if (!status?.configured) return "Not configured";
  if (status.connection_ok === true) return "Connected";
  if (status.connection_ok === false) return "Connection failed";
  return "Configured";
}

function formatSyncResult(result) {
  if (!result) return "";
  return (
    `${result.created ?? 0} created, ` +
    `${result.updated ?? 0} updated, ` +
    `${result.skipped ?? 0} skipped, ` +
    `${(result.errors || []).length} error(s)`
  );
}

export default function Settings() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Form inputs. The token is never populated from the server — it is
  // write-only from the browser to the local backend.
  const [token, setToken] = useState("");
  const [databaseId, setDatabaseId] = useState("");

  const [busy, setBusy] = useState(""); // "saving" | "testing" | "syncing" | "clearing"
  const [message, setMessage] = useState("");
  const [syncResult, setSyncResult] = useState(null);

  async function loadStatus() {
    try {
      setLoading(true);
      const loaded = await getNotionStatus();
      setStatus(loaded);
      setDatabaseId(loaded?.database_id || "");
      setError("");
    } catch (err) {
      setError(err.message || loadError);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function handleSave(event) {
    event.preventDefault();
    if (!token.trim() || !databaseId.trim()) {
      setMessage("Enter both the integration token and the database id.");
      return;
    }
    try {
      setBusy("saving");
      const result = await saveNotionConfig({
        token: token.trim(),
        database_id: databaseId.trim(),
      });
      // Never keep the token in state after saving.
      setToken("");
      setStatus(result);
      setMessage(result.message || "Saved.");
    } catch (exc) {
      setMessage(exc.message || "Failed to save Notion configuration.");
    } finally {
      setBusy("");
    }
  }

  async function handleTest() {
    try {
      setBusy("testing");
      const loaded = await getNotionStatus();
      setStatus(loaded);
      setMessage(loaded.message || "Refreshed status.");
    } catch (exc) {
      setMessage(exc.message || "Failed to refresh status.");
    } finally {
      setBusy("");
    }
  }

  async function handleSync() {
    try {
      setBusy("syncing");
      setSyncResult(null);
      const result = await syncNotion({});
      setSyncResult(result);
      setMessage(result.message || formatSyncResult(result));
    } catch (exc) {
      setMessage(exc.message || "Failed to sync to Notion.");
    } finally {
      setBusy("");
    }
  }

  async function handleClear() {
    try {
      setBusy("clearing");
      const result = await deleteNotionConfig();
      setStatus(result);
      setDatabaseId("");
      setToken("");
      setSyncResult(null);
      setMessage(result.message || "Notion configuration removed.");
    } catch (exc) {
      setMessage(exc.message || "Failed to remove configuration.");
    } finally {
      setBusy("");
    }
  }

  if (loading) {
    return <p>Loading settings…</p>;
  }

  return (
    <section>
      <h1>Settings</h1>

      <h2>Notion Integration</h2>
      <p className="muted-text">
        Sync opportunities to your Notion "Government Bid Tracker" database.
        Syncing dedups by solicitation number (or title) — existing pages are
        updated in place rather than duplicated.
      </p>

      <div className="edit-panel">
        <div className="button-row" style={{ marginBottom: "0.75rem" }}>
          <StatusBadge status={connectionLabel(status)} />
          {status?.configured && status?.database_id ? (
            <span className="muted-text">Database id: {status.database_id}</span>
          ) : null}
        </div>

        <form className="portal-cred-fields" onSubmit={handleSave}>
          <label className="form-field">
            Integration token
            <input
              type="password"
              autoComplete="new-password"
              value={token}
              placeholder="Never shown back; stored in the OS keychain"
              onChange={(event) => setToken(event.target.value)}
            />
          </label>
          <label className="form-field">
            Database id
            <input
              type="text"
              autoComplete="off"
              value={databaseId}
              placeholder="The Government Bid Tracker database id"
              onChange={(event) => setDatabaseId(event.target.value)}
            />
          </label>
        </form>

        <div className="button-row">
          <button
            className="primary-button"
            type="button"
            disabled={busy === "saving"}
            onClick={handleSave}
          >
            {busy === "saving" ? "Saving…" : "Save"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy === "testing"}
            onClick={handleTest}
          >
            {busy === "testing" ? "Testing…" : "Test connection"}
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={!status?.configured || busy === "syncing"}
            onClick={handleSync}
          >
            {busy === "syncing" ? "Syncing…" : "Sync opportunities to Notion"}
          </button>
          {status?.configured ? (
            <button
              className="secondary-button"
              type="button"
              disabled={busy === "clearing"}
              onClick={handleClear}
            >
              {busy === "clearing" ? "Removing…" : "Remove configuration"}
            </button>
          ) : null}
        </div>

        {message ? (
          <p className="muted-text notice-text" role="status" aria-live="polite">
            {message}
          </p>
        ) : null}
        {error ? <LoadError message={error} onRetry={loadStatus} /> : null}

        {syncResult ? (
          <div className="pursuit-result">
            <h3>Last sync</h3>
            <p className="muted-text">{formatSyncResult(syncResult)}</p>
            {syncResult.errors?.length ? (
              <ul>
                {syncResult.errors.slice(0, 10).map((err, index) => (
                  <li key={index}>{err}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}

        <p className="muted-text">
          The integration token is stored in your operating system keychain
          (Windows Credential Manager / macOS Keychain / Secret Service) — never
          in the app database, git, or logs, and never shown back to you.
        </p>
      </div>

      <h2>How to set up</h2>
      <ol className="muted-text">
        <li>
          Create an internal integration at{" "}
          <a href="https://www.notion.so/my-integrations" target="_blank" rel="noreferrer">
            notion.so/my-integrations
          </a>{" "}
          and copy its token.
        </li>
        <li>
          Open your "Government Bid Tracker" database in Notion, and via the
          "..." menu → Connections, share it with your integration.
        </li>
        <li>
          Copy the database id from its URL (the 32-character id before{" "}
          <code>?v=</code>), then paste the token and database id above and click
          Save.
        </li>
      </ol>
    </section>
  );
}
