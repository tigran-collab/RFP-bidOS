import { useEffect, useState } from "react";

import { getSources, scrapeEnabledSources, scrapeSource } from "../api.js";

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
      `${result.skipped_duplicates} duplicates skipped`
    );
  }

  return (
    `${result.records_found} records found, ` +
    `${result.created_count} created, ` +
    `${result.skipped_duplicates} duplicates skipped`
  );
}

export default function Scraper() {
  const [sources, setSources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scraping, setScraping] = useState("");
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
              <th>Type</th>
              <th>Base URL</th>
              <th>Enabled</th>
              <th>Notes</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((source) => (
              <tr key={source.id}>
                <td>{source.name}</td>
                <td>{source.source_type}</td>
                <td>{source.base_url || ""}</td>
                <td>{source.enabled ? "Yes" : "No"}</td>
                <td>{source.notes || ""}</td>
                <td>
                  <button
                    className="primary-button"
                    type="button"
                    disabled={!source.enabled || scraping !== ""}
                    onClick={() => runSourceScrape(source)}
                  >
                    {scraping === String(source.id) ? "Scraping..." : "Scrape Source"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
