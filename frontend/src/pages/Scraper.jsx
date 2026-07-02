import { useEffect, useState } from "react";

import {
  checkSourceAuthStatus,
  getSourceScraperCapabilities,
  getSources,
  previewSource,
  scrapeEnabledSources,
  scrapeSource,
  seedSources,
  updateSource,
} from "../api.js";

const errorMessage = "Failed to load source data. Is the backend running?";

const PORTAL_TYPES = [
  "",
  "Generic Public",
  "BidNet",
  "PlanetBids",
  "SAM.gov",
  "Bonfire",
  "OpenGov",
  "DemandStar",
  "Other",
];

const AUTHENTICATED_PORTALS = new Set(["BidNet", "PlanetBids", "Bonfire", "OpenGov", "DemandStar"]);

function formatResult(result) {
  if (!result) {
    return "";
  }

  const relevance =
    result.candidates_filtered_relevance !== undefined
      ? `, ${result.candidates_filtered_quality || 0} quality filtered, ` +
        `${result.candidates_filtered_relevance || 0} relevance filtered, ` +
        `${result.relevant || 0} relevant, ${result.maybe_relevant || 0} maybe, ` +
        `${result.as_needed_warning_count || 0} as-needed warnings`
      : "";

  if (result.sources_scraped !== undefined) {
    return (
      `${result.sources_scraped} sources scraped, ` +
      `${result.records_found ?? 0} kept${relevance}, ` +
      `${result.created_count ?? 0} created, ` +
      `${result.updated_count || 0} updated, ` +
      `${result.skipped_duplicates ?? 0} duplicates skipped`
    );
  }

  return (
    `${result.records_found ?? 0} kept${relevance}, ` +
    `${result.created_count ?? 0} created, ` +
    `${result.updated_count || 0} updated, ` +
    `${result.skipped_duplicates ?? 0} duplicates skipped`
  );
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString();
}

function CapabilitiesNotice({ source, edit, capabilities }) {
  // If we have a fetched capabilities object, use its message directly.
  if (capabilities) {
    if (!capabilities.supports_authenticated_scrape) {
      return (
        <p className="muted-text notice-text">
          {capabilities.message}
        </p>
      );
    }
    return null;
  }

  // Fallback: derive from local state.
  const portalType = edit.portal_type || source.portal_type || "";
  const requiresCreds = Boolean(edit.requires_credentials);

  if (portalType === "BidNet") {
    return (
      <p className="muted-text notice-text">
        BidNet credentials can be configured here for future authenticated access.
        Authenticated scraping is not enabled in this phase.
      </p>
    );
  }

  if (requiresCreds && AUTHENTICATED_PORTALS.has(portalType)) {
    return (
      <p className="muted-text notice-text">
        {portalType} is configured as a credentialed source.
        Authenticated scraping is not enabled in this phase.
      </p>
    );
  }

  if (requiresCreds) {
    return (
      <p className="muted-text notice-text">
        This source requires credentials. Authenticated scraping is not enabled in this phase.
      </p>
    );
  }

  return null;
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
  const [capabilities, setCapabilities] = useState({});
  const [seeding, setSeeding] = useState(false);
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
              portal_type: source.portal_type || "",
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
    } catch (err) {
      setError(err.message || "Failed to scrape source.");
    } finally {
      setScraping("");
    }
  }

  async function runSourcePreview(source) {
    try {
      setPreviewing(String(source.id));
      const result = await previewSource(source.id);
      setPreview({ sourceName: source.name, result });
      setMessage(
        `${source.name}: ${result.candidates_kept} kept, ` +
          `${result.candidates_filtered_quality || 0} quality filtered, ` +
          `${result.candidates_filtered_relevance || 0} relevance filtered ` +
          `(of ${result.total_candidates_found} found)`,
      );
      setError("");
    } catch (err) {
      setError(err.message || "Failed to preview source.");
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
    } catch (err) {
      setError(err.message || "Failed to scrape enabled sources.");
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
      const edit = sourceEdits[source.id] || {};
      await updateSource(source.id, {
        ...edit,
        portal_type: edit.portal_type || null,
      });
      await loadSources();
      setMessage(`${source.name}: credential settings saved`);
      setError("");
    } catch (err) {
      setError(err.message || "Failed to save credential settings.");
    } finally {
      setSavingSource("");
    }
  }

  async function runSeedSources() {
    try {
      setSeeding(true);
      const result = await seedSources();
      await loadSources();
      setMessage(
        `Sources seeded: ${result.created} created, ${result.updated} updated, ` +
          `${result.skipped_existing} already present`,
      );
      setError("");
    } catch (err) {
      setError(err.message || "Failed to seed sources.");
    } finally {
      setSeeding(false);
    }
  }

  async function fetchCapabilities(source) {
    try {
      const result = await getSourceScraperCapabilities(source.id);
      setCapabilities((current) => ({ ...current, [source.id]: result }));
    } catch {
      // Non-fatal: capabilities notice will fall back to local state.
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
    } catch (err) {
      setError(err.message || "Failed to check auth status.");
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
        <button
          className="secondary-button"
          type="button"
          disabled={seeding}
          onClick={runSeedSources}
        >
          {seeding ? "Seeding..." : "Seed Sources"}
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
              const displayPortal = edit.portal_type || source.portal_type || "Generic Public";
              return (
              <tr key={source.id}>
                <td>
                  <strong>{source.name}</strong>
                  <div className="muted-text">{source.source_type}</div>
                  <div className="muted-text">
                    Portal: {displayPortal}
                    {source.state ? ` · ${source.state}` : ""}
                  </div>
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
                    <label>
                      Portal Type
                      <select
                        value={edit.portal_type || ""}
                        onChange={(event) =>
                          updateSourceEdit(source.id, "portal_type", event.target.value)
                        }
                      >
                        {PORTAL_TYPES.map((pt) => (
                          <option key={pt} value={pt}>{pt || "- Select -"}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      Credential Type
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
                    </label>
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
                    <CapabilitiesNotice source={source} edit={edit} capabilities={capabilities[source.id]} />
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
                      onClick={() => fetchCapabilities(source)}
                    >
                      Capabilities
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
                  <th>Relevance</th>
                  <th>Keywords</th>
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
                    <td>
                      {candidate.relevance_decision || ""}
                      {candidate.relevance_score !== null && candidate.relevance_score !== undefined
                        ? ` (${candidate.relevance_score})`
                        : ""}
                      {candidate.as_needed_warning ? (
                        <div className="notice-text">As-needed caution</div>
                      ) : null}
                    </td>
                    <td>{candidate.keyword_matches?.join(", ") || ""}</td>
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
