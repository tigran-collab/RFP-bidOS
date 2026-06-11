import { useEffect, useState } from "react";

import {
  checkSourceAuthStatus,
  getSources,
  previewSource,
  scrapeEnabledSources,
  scrapeSource,
  updateSource,
} from "../api.js";

const errorMessage = "Failed to load source data. Is the backend running?";

function formatResult(result) {
  if (!result) {
    return "";
  }

  if (result.sources_scraped !== undefined) {
    return (
      `${result.sources_scraped} sources scraped, ` +
      `${result.records_found} records found, ` +
      `${result.created_count} created, ` +
      `${result.updated_count || 0} updated, ` +
      `${result.skipped_duplicates} duplicates skipped`
    );
  }

  return (
    `${result.records_found} records found, ` +
    `${result.created_count} created, ` +
    `${result.updated_count || 0} updated, ` +
    `${result.skipped_duplicates} duplicates skipped`
  );
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString();
}

export default function Scraper() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState("");
  const [previewing, setPreviewing] = useState("");
  const [preview, setPreview] = useState(null);
  const [sourceEdits, setSourceEdits] = useState({});
  const [savingSource, setSavingSource] = useState("");
  const [checkingAuth, setCheckingAuth] = useState("");
  const [authResults, setAuthResults] = useState({});
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadSources() {
    try {
      setLoading(true);
      const loadedSources = await getSources();
      setSources(loadedSources);
      setSourceEdits(
        Object.fromEntries(
          loadedSources.map((source) => [
            source.id,
            {
              requires_credentials: Boolean(source.requires_credentials),
              credential_type: source.credential_type || "",
              credential_username: source.credential_username || "",
              credential_secret_ref: source.credential_secret_ref || "",
              credential_notes: source.credential_notes || "",
            },
          ]),
        ),
      );
      setError("");
    } catch {
      setError(errorMessage);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSources();
  }, []);

  async function runSourceScrape(source) {
    try {
      setScraping(String(source.id));
      const result = await scrapeSource(source.id);
      setMessage(`${source.name}: ${formatResult(result)}`);
      setError("");
    } catch {
      setError("Failed to scrape source.");
    } finally {
      setScraping("");
    }
  }

  async function runSourcePreview(source) {
    try {
      setPreviewing(String(source.id));
      const result = await previewSource(source.id);
      setPreview({ sourceName: source.name, result });
      setMessage(`${source.name}: ${result.records_found} preview candidates`);
      setError("");
    } catch {
      setError("Failed to preview source.");
    } finally {
      setPreviewing("");
    }
  }

  async function runEnabledScrape() {
    try {
      setScraping("enabled");
      const result = await scrapeEnabledSources();
      setMessage(formatResult(result));
      setError("");
    } catch {
      setError("Failed to scrape enabled sources.");
    } finally {
      setScraping("");
    }
  }

  function updateSourceEdit(sourceId, field, value) {
    setSourceEdits((current) => ({
      ...current,
      [sourceId]: {
        ...current[sourceId],
        [field]: value,
      },
    }));
  }

  async function saveSourceCredentials(source) {
    try {
      setSavingSource(String(source.id));
      await updateSource(source.id, sourceEdits[source.id]);
      await loadSources();
      setMessage(`${source.name}: credential settings saved`);
      setError("");
    } catch {
      setError("Failed to save credential settings.");
    } finally {
      setSavingSource("");
    }
  }

  async function checkAuthStatus(source) {
    try {
      setCheckingAuth(String(source.id));
      const result = await checkSourceAuthStatus(source.id);
      setAuthResults((current) => ({ ...current, [source.id]: result }));
      await loadSources();
      setMessage(`${source.name}: ${result.auth_status}`);
      setError("");
    } catch {
      setError("Failed to check auth status.");
    } finally {
      setCheckingAuth("");
    }
  }

  if (loading) {
    return <p>Loading...</p>;
  }

  return (
    <section>
      <h1>Scraper</h1>
      <div className="page-actions">
        <button
          className="primary-button"
          type="button"
          disabled={scraping !== ""}
          onClick={runEnabledScrape}
        >
          {scraping === "enabled" ? "Scraping..." : "Scrape Enabled Sources"}
        </button>
      </div>
      {message ? <p>{message}</p> : null}
      {error ? <p className="error-text">{error}</p> : null}
      {!sources.length ? (
        <p>No sources found.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Source URL</th>
              <th>Enabled</th>
              <th>Last Scrape</th>
              <th>Last Stats</th>
              <th>Auth</th>
              <th>Credential Setup</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => {
              const edit = sourceEdits[source.id] || {};
              const authResult = authResults[source.id];
              const isBidNet = `${source.name} ${source.base_url || ""}`
                .toLowerCase()
                .includes("bidnet");
              return (
              <tr key={source.id}>
                <td>
                  <strong>{source.name}</strong>
                  <div className="muted-text">{source.source_type}</div>
                </td>
                <td className="break-text">{source.base_url || ""}</td>
                <td>{source.enabled ? "Yes" : "No"}</td>
                <td>{formatDate(source.last_scrape_at)}</td>
                <td>{source.last_scrape_summary || ""}</td>
                <td>
                  {source.requires_credentials ? "Credentials required" : "Public"}
                  {source.auth_status ? (
                    <div className="muted-text">{source.auth_status}</div>
                  ) : null}
                  {source.auth_last_checked_at ? (
                    <div className="muted-text">
                      Checked {formatDate(source.auth_last_checked_at)}
                    </div>
                  ) : null}
                </td>
                <td>
                  <div className="credential-grid">
                    <label>
                      <input
                        type="checkbox"
                        checked={Boolean(edit.requires_credentials)}
                        onChange={(event) =>
                          updateSourceEdit(
                            source.id,
                            "requires_credentials",
                            event.target.checked,
                          )
                        }
                      />
                      Requires Credentials
                    </label>
                    <select
                      value={edit.credential_type || ""}
                      onChange={(event) =>
                        updateSourceEdit(source.id, "credential_type", event.target.value)
                      }
                    >
                      <option value="">None</option>
                      <option value="Manual">Manual</option>
                      <option value="Environment">Environment</option>
                      <option value="Future Secret Store">Future Secret Store</option>
                    </select>
                    <input
                      type="text"
                      value={edit.credential_username || ""}
                      placeholder="Username"
                      onChange={(event) =>
                        updateSourceEdit(source.id, "credential_username", event.target.value)
                      }
                    />
                    <input
                      type="text"
                      value={edit.credential_secret_ref || ""}
                      placeholder="Secret reference"
                      onChange={(event) =>
                        updateSourceEdit(source.id, "credential_secret_ref", event.target.value)
                      }
                    />
                    <textarea
                      value={edit.credential_notes || ""}
                      placeholder="Credential notes"
                      rows="2"
                      onChange={(event) =>
                        updateSourceEdit(source.id, "credential_notes", event.target.value)
                      }
                    />
                    {isBidNet ? (
                      <p className="muted-text">
                        BidNet credentials can be configured for future authenticated access.
                        Authenticated scraping is not enabled in this phase.
                      </p>
                    ) : null}
                    {authResult?.missing_fields?.length ? (
                      <p className="error-text">{authResult.missing_fields.join("; ")}</p>
                    ) : null}
                  </div>
                </td>
                <td>
                  <div className="button-row">
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={savingSource !== ""}
                      onClick={() => saveSourceCredentials(source)}
                    >
                      {savingSource === String(source.id) ? "Saving..." : "Save"}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={checkingAuth !== ""}
                      onClick={() => checkAuthStatus(source)}
                    >
                      {checkingAuth === String(source.id) ? "Checking..." : "Check Auth Status"}
                    </button>
                    <button
                      className="secondary-button"
                      type="button"
                      disabled={previewing !== "" || scraping !== ""}
                      onClick={() => runSourcePreview(source)}
                    >
                      {previewing === String(source.id) ? "Previewing..." : "Preview"}
                    </button>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={!source.enabled || scraping !== ""}
                    onClick={() => runSourceScrape(source)}
                  >
                    {scraping === String(source.id) ? "Scraping..." : "Scrape Source"}
                  </button>
                  </div>
                </td>
              </tr>
            );
            })}
          </tbody>
        </table>
      )}
      {preview ? (
        <section className="preview-section">
          <h2>Preview: {preview.sourceName}</h2>
          {preview.result.errors?.length ? (
            <p className="error-text">{preview.result.errors.join("; ")}</p>
          ) : null}
          {!preview.result.candidates?.length ? (
            <p>No preview candidates found.</p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Agency</th>
                  <th>Due Date</th>
                  <th>Detail URL</th>
                  <th>Confidence</th>
                  <th>Service</th>
                  <th>Docs</th>
                </tr>
              </thead>
              <tbody>
                {preview.result.candidates.map((candidate, index) => (
                  <tr key={`${candidate.detail_url || candidate.source_url}-${index}`}>
                    <td>{candidate.title}</td>
                    <td>{candidate.agency || ""}</td>
                    <td>{candidate.due_date ? new Date(candidate.due_date).toLocaleString() : ""}</td>
                    <td className="break-text">{candidate.detail_url || candidate.source_url || ""}</td>
                    <td>{candidate.confidence_score}</td>
                    <td>{candidate.service_type || ""}</td>
                    <td>{candidate.document_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      ) : null}
    </section>
  );
}
