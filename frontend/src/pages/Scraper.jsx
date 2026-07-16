import { useEffect, useState } from "react";

import {
  getSources,
  previewSource,
  scrapeEnabledSources,
  scrapeSource,
  seedSources,
  updateSource,
} from "../api.js";

const errorMessage = "Failed to load source data. Is the backend running?";

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

export default function Scraper() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState("");
  const [previewing, setPreviewing] = useState("");
  const [preview, setPreview] = useState(null);
  const [togglingSource, setTogglingSource] = useState("");
  const [seeding, setSeeding] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  async function loadSources() {
    try {
      setLoading(true);
      setSources(await getSources());
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
      const archivedCount = result.archived?.archived_count ?? 0;
      const archivedSuffix = archivedCount
        ? `, ${archivedCount} expired archived`
        : "";
      setMessage(`${formatResult(result)}${archivedSuffix}`);
      setError("");
    } catch (err) {
      setError(err.message || "Failed to scrape enabled sources.");
    } finally {
      setScraping("");
    }
  }

  async function toggleSourceEnabled(source) {
    try {
      setTogglingSource(String(source.id));
      await updateSource(source.id, { enabled: !source.enabled });
      await loadSources();
      setMessage(`${source.name}: ${source.enabled ? "disabled" : "enabled"}.`);
      setError("");
    } catch (err) {
      setError(err.message || "Failed to update source.");
    } finally {
      setTogglingSource("");
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
              <th>Access</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>
                  <strong>{source.name}</strong>
                  <div className="muted-text">{source.source_type}</div>
                  <div className="muted-text">
                    {source.portal_type || "Generic Public"}
                    {source.state ? ` · ${source.state}` : ""}
                  </div>
                </td>
                <td className="break-text">{source.base_url || ""}</td>
                <td>
                  <label className="portal-toggle">
                    <input
                      type="checkbox"
                      checked={Boolean(source.enabled)}
                      disabled={togglingSource !== ""}
                      aria-label={`Enable ${source.name}`}
                      onChange={() => toggleSourceEnabled(source)}
                    />
                    {source.enabled ? "On" : "Off"}
                  </label>
                </td>
                <td>{formatDate(source.last_scrape_at)}</td>
                <td>{source.last_scrape_summary || ""}</td>
                <td>
                  {source.requires_credentials ? "Credentials required" : "Public"}
                  {source.auth_status ? (
                    <div className="muted-text">{source.auth_status}</div>
                  ) : null}
                  {source.requires_credentials ? (
                    <div className="muted-text">
                      Manage login on the Portals tab.
                    </div>
                  ) : null}
                </td>
                <td>
                  <div className="button-row">
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
                      {scraping === String(source.id) ? "Scraping..." : "Scrape"}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
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
