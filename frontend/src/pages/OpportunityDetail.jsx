import { useEffect, useState } from "react";

import {
  aiEvaluateOpportunity,
  downloadOpportunityDocuments,
  extractOpportunityRequirements,
  getOpportunity,
  getOpportunityDocuments,
  getOpportunityEvaluations,
  getOpportunityRequirements,
  parseOpportunityDocuments,
  scoreOpportunity,
} from "../api.js";
import StatusBadge from "../components/StatusBadge.jsx";

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

function parseList(value) {
  if (!value) {
    return [];
  }
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function FactorList({ items }) {
  if (!items.length) {
    return <p>-</p>;
  }
  return (
    <ul>
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

export default function OpportunityDetail({ opportunityId }) {
  const [opportunity, setOpportunity] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [evaluations, setEvaluations] = useState([]);
  const [requirements, setRequirements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [aiEvaluating, setAiEvaluating] = useState(false);
  const [extracting, setExtracting] = useState(false);
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
        const [
          opportunityResult,
          documentsResult,
          evaluationsResult,
          requirementsResult,
        ] = await Promise.all([
          getOpportunity(opportunityId),
          getOpportunityDocuments(opportunityId),
          getOpportunityEvaluations(opportunityId),
          getOpportunityRequirements(opportunityId),
        ]);
        setOpportunity(opportunityResult);
        setDocuments(documentsResult);
        setEvaluations(evaluationsResult);
        setRequirements(requirementsResult);
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

  async function runParse() {
    try {
      setParsing(true);
      const result = await parseOpportunityDocuments(opportunityId);
      setDocuments(await getOpportunityDocuments(opportunityId));
      setActionMessage(
        `${result.parsed_count} parsed, ${result.skipped_count} skipped, ${result.failed_count} failed.`
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch {
      setActionError("Failed to parse documents. Is the backend running?");
    } finally {
      setParsing(false);
    }
  }

  async function runAiEvaluation() {
    try {
      setAiEvaluating(true);
      const result = await aiEvaluateOpportunity(opportunityId);
      const [opportunityResult, evaluationsResult] = await Promise.all([
        getOpportunity(opportunityId),
        getOpportunityEvaluations(opportunityId),
      ]);
      setOpportunity(opportunityResult);
      setEvaluations(evaluationsResult);
      if (result.error) {
        setActionError(result.error);
        setActionMessage("");
      } else {
        setActionMessage("Local AI evaluation updated.");
        setActionError("");
      }
    } catch {
      setActionError(
        "Local AI model is not available. Start Ollama and make sure the model is installed."
      );
    } finally {
      setAiEvaluating(false);
    }
  }

  async function runRequirementExtraction() {
    try {
      setExtracting(true);
      const result = await extractOpportunityRequirements(opportunityId);
      setRequirements(await getOpportunityRequirements(opportunityId));
      setActionMessage(`${result.requirements_count} requirements extracted.`);
      setActionError("");
    } catch (err) {
      setActionError(err.message || "Failed to extract requirements.");
    } finally {
      setExtracting(false);
    }
  }

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  const latestEvaluation = evaluations[0] || null;
  const busy = scoring || downloading || parsing || aiEvaluating || extracting;

  return (
    <section>
      <h1>{opportunity.title}</h1>
      <div className="page-actions">
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runScore}
        >
          {scoring ? "Scoring..." : "Run Bid/No-Bid Score"}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runDownload}
        >
          {downloading ? "Downloading..." : "Download Documents"}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runParse}
        >
          {parsing ? "Parsing..." : "Parse Documents"}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runAiEvaluation}
        >
          {aiEvaluating ? "Evaluating..." : "Run Local AI Evaluation"}
        </button>
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runRequirementExtraction}
        >
          {extracting ? "Extracting..." : "Extract Requirements"}
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
        <DetailRow label="AI recommendation" value={opportunity.ai_recommendation} />
        <DetailRow label="AI score" value={opportunity.ai_score} />
        <DetailRow label="AI reason" value={opportunity.ai_reason} />
        <DetailRow label="AI risk level" value={opportunity.ai_risk_level} />
        <DetailRow label="Status" value={opportunity.status} />
      </dl>
      <h2>Local AI Evaluation</h2>
      {!latestEvaluation ? (
        <p>No local AI evaluation found.</p>
      ) : (
        <dl className="detail-grid">
          <DetailRow label="AI recommendation" value={latestEvaluation.recommendation} />
          <DetailRow label="AI score" value={latestEvaluation.score} />
          <DetailRow label="Risk level" value={latestEvaluation.risk_level} />
          <DetailRow label="Pursuit effort" value={latestEvaluation.pursuit_effort} />
          <DetailRow label="Reason" value={latestEvaluation.reason} />
          <DetailRow
            label="Positive factors"
            value={<FactorList items={parseList(latestEvaluation.positive_factors_json)} />}
          />
          <DetailRow
            label="Negative factors"
            value={<FactorList items={parseList(latestEvaluation.negative_factors_json)} />}
          />
          <DetailRow
            label="Missing information"
            value={<FactorList items={parseList(latestEvaluation.missing_information_json)} />}
          />
          <DetailRow
            label="Questions to verify"
            value={<FactorList items={parseList(latestEvaluation.questions_to_verify_json)} />}
          />
          <DetailRow
            label="Recommended next action"
            value={latestEvaluation.recommended_next_action}
          />
        </dl>
      )}
      <h2>Requirements / Compliance</h2>
      {!requirements.length ? (
        <p>No requirements found.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Title</th>
              <th>Mandatory</th>
              <th>Status</th>
              <th>Source Page</th>
              <th>Assigned Section</th>
              <th>Requirement</th>
            </tr>
          </thead>
          <tbody>
            {requirements.map((requirement) => (
              <tr key={requirement.id}>
                <td>{requirement.requirement_type || "Other"}</td>
                <td>{requirement.title || ""}</td>
                <td>{requirement.mandatory ? "Yes" : "No"}</td>
                <td>
                  <StatusBadge status={requirement.status || "Needs Review"} />
                </td>
                <td>{requirement.source_page ?? ""}</td>
                <td>{requirement.assigned_response_section || ""}</td>
                <td>
                  <details>
                    <summary>View</summary>
                    <p>{requirement.requirement_text}</p>
                  </details>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
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
              <th>Extracted Text Path</th>
              <th>Source URL</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.filename}</td>
                <td>{document.file_type || ""}</td>
                <td>{document.parsed_status}</td>
                <td>{document.extracted_text_path || ""}</td>
                <td>{document.source_url || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
