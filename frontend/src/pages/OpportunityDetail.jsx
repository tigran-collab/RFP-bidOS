import { useCallback, useEffect, useState } from "react";

import {
  aiEvaluateOpportunity,
  analyzeOpportunityDocuments,
  attachManualDocumentUrl,
  deleteOpportunity,
  downloadDocument,
  downloadOpportunityDocuments,
  downloadOpportunityPortalDocuments,
  extractOpportunityLogistics,
  extractOpportunityRequirements,
  generateAiSummary,
  getDocumentBrief,
  getDocumentFileUrl,
  getLogisticsQA,
  getOpportunity,
  getOpportunityDocuments,
  getOpportunityEvaluations,
  getOpportunityRequirements,
  parseOpportunityDocuments,
  runLogisticsQA,
  runPursuitPrep,
  scoreOpportunity,
  updateOpportunity,
} from "../api.js";
import OpportunityFields, {
  buildOpportunityPatch,
} from "../components/OpportunityFields.jsx";
import LoadError from "../components/LoadError.jsx";
import StatusBadge from "../components/StatusBadge.jsx";

function toEditValues(o) {
  const datePart = (value) => (value ? value.slice(0, 10) : "");
  return {
    title: o.title || "",
    agency: o.agency || "",
    solicitation_number: o.solicitation_number || "",
    source_url: o.source_url || "",
    portal_url: o.portal_url || "",
    location: o.location || "",
    service_type: o.service_type || "",
    contract_type: o.contract_type || "",
    estimated_value: o.estimated_value ?? "",
    due_date: datePart(o.due_date),
    q_and_a_deadline: datePart(o.q_and_a_deadline),
    pre_bid_date: datePart(o.pre_bid_date),
    pre_bid_mandatory: Boolean(o.pre_bid_mandatory),
    submission_method: o.submission_method || "",
    submission_portal: o.submission_portal || "",
    required_forms_summary: o.required_forms_summary || "",
    review_status: o.review_status || "New",
    priority: o.priority || "",
    next_action: o.next_action || "",
    description: o.description || "",
    notes: o.notes || "",
    review_notes: o.review_notes || "",
  };
}

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

export default function OpportunityDetail({ opportunityId, onNavigate }) {
  const [opportunity, setOpportunity] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [evaluations, setEvaluations] = useState([]);
  const [requirements, setRequirements] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const [pursuitResult, setPursuitResult] = useState(null);
  const [downloading, setDownloading] = useState(false);
  const [portalDownloading, setPortalDownloading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [docBusyId, setDocBusyId] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [aiEvaluating, setAiEvaluating] = useState(false);
  const [aiSummarizing, setAiSummarizing] = useState(false);
  const [aiSummaryNotice, setAiSummaryNotice] = useState("");
  const [analyzingDocs, setAnalyzingDocs] = useState(false);
  const [docBrief, setDocBrief] = useState(null);
  const [extracting, setExtracting] = useState(false);
  const [extractingLogistics, setExtractingLogistics] = useState(false);
  const [runningQA, setRunningQA] = useState(false);
  const [logisticsQA, setLogisticsQA] = useState(null);
  const [editing, setEditing] = useState(false);
  const [editValues, setEditValues] = useState({});
  const [savingEdit, setSavingEdit] = useState(false);
  const [docUrl, setDocUrl] = useState("");
  const [docLabel, setDocLabel] = useState("");
  const [attachingDoc, setAttachingDoc] = useState(false);
  const [actionMessage, setActionMessage] = useState("");
  const [actionError, setActionError] = useState("");
  const [error, setError] = useState("");

  const loadOpportunity = useCallback(async () => {
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
        qaResult,
      ] = await Promise.all([
        getOpportunity(opportunityId),
        getOpportunityDocuments(opportunityId),
        getOpportunityEvaluations(opportunityId),
        getOpportunityRequirements(opportunityId),
        getLogisticsQA(opportunityId),
      ]);
      setOpportunity(opportunityResult);
      setDocuments(documentsResult ?? []);
      setEvaluations(evaluationsResult ?? []);
      setRequirements(requirementsResult ?? []);
      setLogisticsQA(qaResult && qaResult.qa_status ? qaResult : null);
      setError("");
      // The brief 404s until the agent has run once — absence is normal.
      try {
        setDocBrief(await getDocumentBrief(opportunityId));
      } catch {
        setDocBrief(null);
      }
    } catch (err) {
      setError(err.message || errorMessage);
    } finally {
      setLoading(false);
    }
  }, [opportunityId]);

  useEffect(() => {
    loadOpportunity();
  }, [loadOpportunity]);

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

  async function runPrep() {
    try {
      setPreparing(true);
      const result = await runPursuitPrep(opportunityId);
      setPursuitResult(result);
      const [opportunityResult, documentsResult, evaluationsResult, requirementsResult] =
        await Promise.all([
          getOpportunity(opportunityId),
          getOpportunityDocuments(opportunityId),
          getOpportunityEvaluations(opportunityId),
          getOpportunityRequirements(opportunityId),
        ]);
      setOpportunity(opportunityResult);
      setDocuments(documentsResult);
      setEvaluations(evaluationsResult);
      setRequirements(requirementsResult);
      setActionMessage(
        `Pursuit prep ${result.final_status} -> next action: ${result.next_action}`,
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch {
      setActionError("Failed to run pursuit prep. Is the backend running?");
    } finally {
      setPreparing(false);
    }
  }

  async function runDelete() {
    const confirmed = window.confirm(
      `Delete "${opportunity?.title || `opportunity ${opportunityId}`}"?\n\n` +
        "This permanently removes the opportunity and its documents, " +
        "requirements, evaluations, and QA results.",
    );
    if (!confirmed) {
      return;
    }
    try {
      setDeleting(true);
      await deleteOpportunity(opportunityId);
      if (onNavigate) {
        onNavigate("opportunities");
      } else {
        setActionMessage("Opportunity deleted.");
      }
    } catch (err) {
      setActionError(err.message || "Failed to delete opportunity.");
      setDeleting(false);
    }
  }

  function startEdit() {
    setEditValues(toEditValues(opportunity));
    setEditing(true);
    setActionMessage("");
    setActionError("");
  }

  function onEditChange(field, value) {
    setEditValues((current) => ({ ...current, [field]: value }));
  }

  async function saveEdit() {
    if (!editValues.title || !editValues.title.trim()) {
      setActionError("Title is required.");
      return;
    }
    try {
      setSavingEdit(true);
      const payload = buildOpportunityPatch(editValues, toEditValues(opportunity));
      const updated = await updateOpportunity(opportunityId, payload);
      setOpportunity(updated);
      setEditing(false);
      setActionMessage("Opportunity updated.");
      setActionError("");
    } catch (err) {
      setActionError(err.message || "Failed to update opportunity.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function attachDoc() {
    const url = docUrl.trim();
    if (!url.startsWith("http://") && !url.startsWith("https://")) {
      setActionError("Document URL must start with http:// or https://");
      return;
    }
    try {
      setAttachingDoc(true);
      const result = await attachManualDocumentUrl(opportunityId, url, docLabel || null);
      setDocuments(await getOpportunityDocuments(opportunityId));
      setDocUrl("");
      setDocLabel("");
      setActionMessage(
        result.status === "exists"
          ? "Document URL was already attached."
          : "Document URL attached (pending download).",
      );
      setActionError("");
    } catch (err) {
      setActionError(err.message || "Failed to attach document URL.");
    } finally {
      setAttachingDoc(false);
    }
  }

  async function runQA() {
    try {
      setRunningQA(true);
      const result = await runLogisticsQA(opportunityId);
      setLogisticsQA(result);
      setActionMessage(
        `Logistics QA: ${result.qa_status} (${result.risk_level} risk), ` +
          `${result.issues?.length || 0} issue(s)`,
      );
      setActionError("");
    } catch {
      setActionError("Failed to run logistics QA. Is the backend running?");
    } finally {
      setRunningQA(false);
    }
  }

  async function runExtractLogistics() {
    try {
      setExtractingLogistics(true);
      const result = await extractOpportunityLogistics(opportunityId);
      setOpportunity(await getOpportunity(opportunityId));
      setActionMessage(
        `Logistics extracted: deadline risk ${result.deadline_risk}, ` +
          `confidence ${result.logistics_confidence_score ?? "-"}` +
          (result.has_parsed_text ? "" : " (no parsed text - metadata only)"),
      );
      setActionError("");
    } catch {
      setActionError("Failed to extract logistics. Is the backend running?");
    } finally {
      setExtractingLogistics(false);
    }
  }

  async function runDownload() {
    try {
      setDownloading(true);
      const result = await downloadOpportunityDocuments(opportunityId);
      setDocuments(await getOpportunityDocuments(opportunityId));
      const discovered =
        result.documents_discovered !== undefined
          ? `${result.documents_discovered} discovered, `
          : "";
      setActionMessage(
        `${discovered}${result.downloaded_count} downloaded, ${result.skipped_count} skipped.`
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch {
      setActionError("Failed to download documents. Is the backend running?");
    } finally {
      setDownloading(false);
    }
  }

  async function runPortalDownload() {
    try {
      setPortalDownloading(true);
      setActionMessage(
        "Opening the portal in a browser window. If a login page appears, " +
          "complete the sign-in — the download continues automatically.",
      );
      setActionError("");
      const result = await downloadOpportunityPortalDocuments(opportunityId);
      setDocuments(await getOpportunityDocuments(opportunityId));
      const loginNote = result.login_performed ? "signed in, " : "";
      setActionMessage(
        `Portal download: ${loginNote}${result.candidates_found} candidates, ` +
          `${result.downloads_attempted} attempted, ` +
          `${result.downloaded_count} downloaded, ${result.skipped_count} skipped.`
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch (err) {
      setActionError(err.message || "Failed to run headed portal download.");
    } finally {
      setPortalDownloading(false);
    }
  }

  async function runSingleDocumentDownload(documentId) {
    try {
      setDocBusyId(documentId);
      const result = await downloadDocument(documentId);
      setDocuments(await getOpportunityDocuments(opportunityId));
      setActionMessage(
        `Document ${documentId}: ${result.downloaded_count} downloaded, ${result.skipped_count} skipped.`
      );
      setActionError(result.errors?.length ? result.errors.join("; ") : "");
    } catch (err) {
      setActionError(err.message || `Failed to download document ${documentId}.`);
    } finally {
      setDocBusyId(null);
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

  async function runAiSummary() {
    try {
      setAiSummarizing(true);
      setAiSummaryNotice("");
      const result = await generateAiSummary(opportunityId);
      if (result.ok) {
        setOpportunity(await getOpportunity(opportunityId));
        setActionMessage("Local AI summary updated.");
        setActionError("");
      } else {
        setAiSummaryNotice(result.message || "Local AI summary is not available.");
      }
    } catch {
      setAiSummaryNotice(
        "Local AI model is not available. Start Ollama and make sure the model is installed."
      );
    } finally {
      setAiSummarizing(false);
    }
  }

  async function runDocumentAgent(refresh = false) {
    try {
      setAnalyzingDocs(true);
      const result = await analyzeOpportunityDocuments(opportunityId, refresh);
      try {
        setDocBrief(await getDocumentBrief(opportunityId));
      } catch {
        setDocBrief(null);
      }
      const warnings = result.errors?.length ? ` Warnings: ${result.errors.join("; ")}` : "";
      setActionMessage(
        `Document agent: ${result.documents_analyzed} analyzed, ` +
          `${result.documents_skipped} already analyzed.${warnings}`,
      );
      setActionError("");
    } catch (err) {
      setActionError(
        err.message ||
          "Document analysis failed. Start Ollama and make sure documents are parsed.",
      );
    } finally {
      setAnalyzingDocs(false);
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
    return <LoadError message={error} onRetry={loadOpportunity} />;
  }

  const latestEvaluation = evaluations[0] || null;
  const busy =
    scoring ||
    preparing ||
    downloading ||
    portalDownloading ||
    parsing ||
    aiEvaluating ||
    aiSummarizing ||
    analyzingDocs ||
    extracting ||
    extractingLogistics ||
    runningQA;

  return (
    <section>
      <h1>{opportunity.title}</h1>
      <div className="page-actions">
        <button
          className="primary-button"
          type="button"
          disabled={busy}
          onClick={runPrep}
        >
          {preparing ? "Running Pursuit Prep..." : "Run Pursuit Prep"}
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={busy || savingEdit || deleting}
          onClick={editing ? () => setEditing(false) : startEdit}
        >
          {editing ? "Cancel Edit" : "Edit Opportunity"}
        </button>
        <button
          className="danger-button"
          type="button"
          disabled={busy || savingEdit || deleting}
          onClick={runDelete}
        >
          {deleting ? "Deleting..." : "Delete"}
        </button>
      </div>
      <div className="action-groups">
        <div className="action-group">
          <span className="action-group-label">Documents</span>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runDownload}
          >
            {downloading ? "Downloading..." : "Download Documents"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runPortalDownload}
          >
            {portalDownloading ? "Opening Portal..." : "Portal Download"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runParse}
          >
            {parsing ? "Parsing..." : "Parse Documents"}
          </button>
        </div>
        <div className="action-group">
          <span className="action-group-label">Analysis</span>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runAiEvaluation}
          >
            {aiEvaluating ? "Evaluating..." : "Local AI Evaluation"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={() => runDocumentAgent(false)}
          >
            {analyzingDocs ? "Analyzing Documents..." : "Analyze Documents"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runRequirementExtraction}
          >
            {extracting ? "Extracting..." : "Extract Requirements"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runExtractLogistics}
          >
            {extractingLogistics ? "Extracting..." : "Extract Logistics"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runQA}
          >
            {runningQA ? "Running QA..." : "Logistics QA"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runScore}
          >
            {scoring ? "Scoring..." : "Bid/No-Bid Score"}
          </button>
        </div>
      </div>
      {actionMessage ? (
        <p role="status" aria-live="polite">
          {actionMessage}
        </p>
      ) : null}
      {actionError ? (
        <p className="error-text" role="status" aria-live="polite">
          {actionError}
        </p>
      ) : null}
      {editing ? (
        <div className="edit-panel">
          <h2>Edit Opportunity</h2>
          <OpportunityFields values={editValues} onChange={onEditChange} />
          <div className="page-actions">
            <button
              className="primary-button"
              type="button"
              disabled={savingEdit}
              onClick={saveEdit}
            >
              {savingEdit ? "Saving..." : "Save Changes"}
            </button>
            <button
              className="secondary-button"
              type="button"
              disabled={savingEdit}
              onClick={() => setEditing(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}
      {pursuitResult ? (
        <div className="pursuit-result">
          <h3>
            Pursuit Prep: {pursuitResult.final_status} {"->"} next action:{" "}
            {pursuitResult.next_action}
          </h3>
          <ul>
            {pursuitResult.step_results.map((step) => (
              <li key={step.step}>
                <strong>{step.step}</strong>: {step.status} - {step.summary}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
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
        <DetailRow
          label="Scraper relevance"
          value={
            opportunity.relevance_decision
              ? `${opportunity.relevance_decision} (${opportunity.relevance_score ?? "-"})`
              : "-"
          }
        />
        <DetailRow label="Keyword matches" value={parseList(opportunity.keyword_matches_json).join(", ")} />
        <DetailRow label="Relevance reason" value={opportunity.relevance_reason} />
        <DetailRow
          label="As-needed caution"
          value={opportunity.as_needed_warning ? "Yes" : "No"}
        />
        <DetailRow label="AI recommendation" value={opportunity.ai_recommendation} />
        <DetailRow label="AI score" value={opportunity.ai_score} />
        <DetailRow label="AI reason" value={opportunity.ai_reason} />
        <DetailRow label="AI risk level" value={opportunity.ai_risk_level} />
        <DetailRow label="Status" value={opportunity.status} />
      </dl>
      <h2>Bid Logistics</h2>
      <dl className="detail-grid">
        <DetailRow label="Due date" value={formatDate(opportunity.due_date)} />
        <DetailRow label="Q&A deadline" value={formatDate(opportunity.q_and_a_deadline)} />
        <DetailRow label="Pre-bid date" value={formatDate(opportunity.pre_bid_date)} />
        <DetailRow
          label="Pre-bid mandatory"
          value={opportunity.pre_bid_mandatory ? "Yes" : "No"}
        />
        <DetailRow label="Submission method" value={opportunity.submission_method} />
        <DetailRow label="Submission portal" value={opportunity.submission_portal} />
        <DetailRow
          label="Required forms"
          value={opportunity.required_forms_summary}
        />
        <DetailRow label="Deadline risk" value={opportunity.deadline_risk} />
        <DetailRow
          label="Logistics confidence"
          value={opportunity.logistics_confidence_score}
        />
        <DetailRow label="Logistics notes" value={opportunity.logistics_notes} />
      </dl>
      <h2>Logistics QA</h2>
      {!logisticsQA ? (
        <p>No logistics QA run yet. Use Run Logistics QA after extracting logistics.</p>
      ) : (
        <dl className="detail-grid">
          <DetailRow label="QA status" value={logisticsQA.qa_status} />
          <DetailRow label="Risk level" value={logisticsQA.risk_level} />
          <DetailRow label="Summary" value={logisticsQA.summary} />
          <DetailRow
            label="Issues"
            value={
              logisticsQA.issues?.length ? (
                <ul>
                  {logisticsQA.issues.map((issue, index) => (
                    <li key={index}>
                      [{issue.risk}] {issue.issue}
                    </li>
                  ))}
                </ul>
              ) : (
                "None"
              )
            }
          />
          <DetailRow
            label="Recommended actions"
            value={
              logisticsQA.recommended_actions?.length ? (
                <ul>
                  {logisticsQA.recommended_actions.map((action, index) => (
                    <li key={index}>{action}</li>
                  ))}
                </ul>
              ) : (
                "None"
              )
            }
          />
          <DetailRow label="Checked at" value={formatDate(logisticsQA.checked_at)} />
        </dl>
      )}
      <h2>AI Summary</h2>
      <div className="pursuit-result">
        <div className="page-actions">
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={runAiSummary}
          >
            {aiSummarizing ? "Generating..." : "Generate AI Summary"}
          </button>
        </div>
        {aiSummaryNotice ? <p className="muted-text">{aiSummaryNotice}</p> : null}
        {opportunity.ai_summary ? (
          <>
            <p style={{ whiteSpace: "pre-wrap" }}>{opportunity.ai_summary}</p>
            <p className="muted-text">
              Generated {formatDate(opportunity.ai_summary_at)}. Advisory only - verify
              against the official solicitation documents.
            </p>
          </>
        ) : (
          !aiSummaryNotice && (
            <p>No AI summary yet. Use Generate AI Summary (local Ollama only).</p>
          )
        )}
      </div>
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
      <h2>Local AI Document Brief</h2>
      {!docBrief ? (
        <p>
          No document analysis yet. Download and parse documents, then use
          Analyze Documents (local Ollama only) to work through every file.
        </p>
      ) : (
        <div>
          {docBrief.brief?.summary ? <p>{docBrief.brief.summary}</p> : null}
          {docBrief.brief?.red_flags?.length ? (
            <div>
              <strong>Red flags</strong>
              <ul>
                {docBrief.brief.red_flags.map((flag) => (
                  <li key={flag}>{flag}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {docBrief.brief?.open_questions?.length ? (
            <div>
              <strong>Open questions for the agency</strong>
              <ul>
                {docBrief.brief.open_questions.map((question) => (
                  <li key={question}>{question}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {docBrief.brief?.facts?.length ? (
            <details>
              <summary>
                Extracted facts ({docBrief.brief.facts.length}, cited by file and chunk)
              </summary>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Category</th>
                    <th>Fact</th>
                    <th>Source</th>
                  </tr>
                </thead>
                <tbody>
                  {docBrief.brief.facts.map((fact, index) => (
                    <tr key={`${fact.source_file}-${fact.chunk}-${index}`}>
                      <td>{fact.category}</td>
                      <td>{fact.detail}</td>
                      <td>
                        {fact.source_file} · chunk {fact.chunk}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          ) : null}
          {docBrief.documents?.length ? (
            <details>
              <summary>Per-document analyses ({docBrief.documents.length})</summary>
              <ul>
                {docBrief.documents.map((doc) => (
                  <li key={doc.id}>
                    <strong>
                      {documents.find((d) => d.id === doc.document_id)?.filename ||
                        `Document ${doc.document_id}`}
                    </strong>{" "}
                    — {doc.status}
                    {doc.truncated ? " (truncated: file larger than the analysis cap)" : ""}
                    {doc.error ? ` — ${doc.error}` : ""}
                    {doc.summary ? <p>{doc.summary}</p> : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
          <p className="muted-text">
            Generated by the local AI document agent ({docBrief.brief?.model_name || "local model"}
            ). Verify every fact against the source files before relying on it.
          </p>
          <button
            className="secondary-button"
            type="button"
            disabled={busy}
            onClick={() => runDocumentAgent(true)}
          >
            {analyzingDocs ? "Re-analyzing..." : "Re-analyze All Documents"}
          </button>
        </div>
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
      <h2>Documents ({documents.length})</h2>
      <div className="manual-doc-row">
        <input
          type="text"
          value={docUrl}
          placeholder="https://example.gov/file.pdf"
          aria-label="Manual document URL"
          onChange={(event) => setDocUrl(event.target.value)}
        />
        <input
          type="text"
          value={docLabel}
          placeholder="Label (optional)"
          aria-label="Manual document label"
          onChange={(event) => setDocLabel(event.target.value)}
        />
        <button
          className="secondary-button"
          type="button"
          disabled={attachingDoc || !docUrl.trim()}
          onClick={attachDoc}
        >
          {attachingDoc ? "Attaching..." : "Attach Document URL"}
        </button>
      </div>
      {!documents.length ? (
        <p>
          No documents found. Use Download Documents to find and fetch document
          links from the source page, or Portal Download for login portals.
        </p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Filename / Link</th>
              <th>File Type</th>
              <th>Status</th>
              <th>Extracted Text Path</th>
              <th>Source URL</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {documents.map((document) => (
              <tr key={document.id}>
                <td>{document.filename || "(discovered link)"}</td>
                <td>{document.file_type || ""}</td>
                <td>
                  {document.path
                    ? document.parsed_status
                    : "Discovered (not downloaded)"}
                </td>
                <td>{document.extracted_text_path || ""}</td>
                <td className="break-text">
                  {document.source_url ? (
                    <a href={document.source_url} target="_blank" rel="noreferrer">
                      {document.source_url}
                    </a>
                  ) : (
                    ""
                  )}
                </td>
                <td>
                  <div className="document-actions">
                    {document.source_url ? (
                      <button
                        className="secondary-button"
                        type="button"
                        disabled={docBusyId === document.id || busy}
                        onClick={() => runSingleDocumentDownload(document.id)}
                      >
                        {docBusyId === document.id ? "Fetching..." : "Fetch File"}
                      </button>
                    ) : null}
                    {document.path ? (
                      <a
                        className="secondary-button button-link"
                        href={getDocumentFileUrl(document.id)}
                      >
                        Download File
                      </a>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
