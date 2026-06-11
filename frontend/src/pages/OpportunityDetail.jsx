import { useEffect, useState } from "react";

import {
  downloadOpportunityDocuments,
  getOpportunity,
  getOpportunityDocuments,
  scoreOpportunity,
} from "../api.js";

const errorMessage = "Failed to load backend data. Is the backend running?";

function formatDate(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toLocaleString();
}

function formatCurrency(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function DetailRow({ label, value }) {
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{value === null || value === undefined || value === "" ? "-" : value}</dd>
    </div>
  );
}

export default function OpportunityDetail({ opportunityId }) {
  const [opportunity, setOpportunity] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadOpportunity() {
      if (!opportunityId) {
        setError(errorMessage);
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        const [opportunityResult, documentsResult] = await Promise.all([
          getOpportunity(opportunityId),
          getOpportunityDocuments(opportunityId),
        ]);
        setOpportunity(opportunityResult);
        setDocuments(documentsResult);
        setError("");
      } catch {
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    }

    loadOpportunity();
  }, [opportunityId]);

  async function runScore() {
    try {
      setScoring(true);
      const result = await scoreOpportunity(opportunityId);
      setOpportunity(result.opportunity);
      setActionMessage("Bid/no-bid score updated.");
      setActionError("");
      setError("");
    } catch {
      setActionError("Failed to score opportunity. Is the backend running?");
    } finally {
      setScoring(false);
    }
  }

  async function runDownload() {
    try {
      setDownloading(true);
      const result = await downloadOpportunityDocuments(opportunityId);
      setDocuments(await getOpportunityDocuments(opportunityId));
      setActionMessage(
        `${result.downloaded_count} downloaded, ${result.skipped_count} skipped.`
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch {
      setActionError("Failed to download documents. Is the backend running?");
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  return (
    <section>
      <h1>{opportunity.title}</h1>
      <div className="page-actions">
        <button
          className="primary-button"
          type="button"
          disabled={scoring || downloading}
          onClick={runScore}
        >
          {scoring ? "Scoring..." : "Run Bid/No-Bid Score"}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={scoring || downloading}
          onClick={runDownload}
        >
          {downloading ? "Downloading..." : "Download Documents"}
        </button>
      </div>
      {actionMessage ? <p>{actionMessage}</p> : null}
      {actionError ? <p className="error-text">{actionError}</p> : null}
      <dl className="detail-grid">
        <DetailRow label="Title" value={opportunity.title} />
        <DetailRow label="Agency" value={opportunity.agency} />
        <DetailRow
          label="Solicitation number"
          value={opportunity.solicitation_number}
        />
        <DetailRow label="Source" value={opportunity.source} />
        <DetailRow label="Source URL" value={opportunity.source_url} />
        <DetailRow label="Portal URL" value={opportunity.portal_url} />
        <DetailRow label="Location" value={opportunity.location} />
        <DetailRow label="Due date" value={formatDate(opportunity.due_date)} />
        <DetailRow
          label="Pre-bid date"
          value={formatDate(opportunity.pre_bid_date)}
        />
        <DetailRow
          label="Pre-bid mandatory"
          value={opportunity.pre_bid_mandatory ? "Yes" : "No"}
        />
        <DetailRow
          label="Q&A deadline"
          value={formatDate(opportunity.q_and_a_deadline)}
        />
        <DetailRow label="Service type" value={opportunity.service_type} />
        <DetailRow label="Contract type" value={opportunity.contract_type} />
        <DetailRow
          label="Estimated value"
          value={formatCurrency(opportunity.estimated_value)}
        />
        <DetailRow label="Bid decision" value={opportunity.bid_decision} />
        <DetailRow label="Bid score" value={opportunity.bid_score} />
        <DetailRow label="Bid reason" value={opportunity.bid_reason} />
        <DetailRow label="Status" value={opportunity.status} />
      </dl>
      <h2>Documents</h2>
      {!documents.length ? (
        <p>No documents found.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Filename</th>
              <th>File Type</th>
              <th>Parsed Status</th>
              <th>Source URL</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.filename}</td>
                <td>{document.file_type || ""}</td>
                <td>{document.parsed_status}</td>
                <td>{document.source_url || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
