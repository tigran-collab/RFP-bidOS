import { useEffect, useState } from "react";

import { getSources, previewSource, scrapeEnabledSources, scrapeSource } from "../api.js";

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
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
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
                    {scraping === String(source.id) ? "Scraping..." : "Scrape Source"}
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
