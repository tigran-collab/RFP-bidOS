export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    let detail = `API request failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      detail = `API request failed: ${response.status}`;
    }
    throw new Error(detail);
  }
  return response.json();
}

function jsonRequest(path, payload, method = "POST") {
  return request(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function getHealth() {
  return request("/health");
}

export function getOperationsDashboard() {
  return request("/dashboard/operations");
}

export function getAiStatus() {
  return request("/ai/status");
}

export function getAiChatStatus() {
  return request("/ai/chat/status");
}

export function sendAiChatMessage(message, context = null) {
  return jsonRequest("/ai/chat", { message, context }, "POST");
}

export function getOpportunities() {
  return request("/opportunities");
}

export function getOpportunity(id) {
  return request(`/opportunities/${id}`);
}

export function getReviewQueue(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, value);
    }
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/opportunities/review-queue${suffix}`);
}

export function reviewOpportunity(id, payload) {
  return jsonRequest(`/opportunities/${id}/review`, payload, "PATCH");
}

export function runPursuitPrep(id, steps) {
  const body = steps ? { steps } : {};
  return jsonRequest(`/opportunities/${id}/pursuit-prep`, body, "POST");
}

export function extractOpportunityLogistics(id) {
  return request(`/opportunities/${id}/extract-logistics`, { method: "POST" });
}

export function runLogisticsQA(id) {
  return request(`/opportunities/${id}/logistics-qa`, { method: "POST" });
}

export function getLogisticsQA(id) {
  return request(`/opportunities/${id}/logistics-qa`);
}

export function scoreOpportunity(id) {
  return request(`/opportunities/${id}/score`, { method: "POST" });
}

export function createOpportunity(payload) {
  return jsonRequest("/opportunities", payload, "POST");
}

export function updateOpportunity(id, payload) {
  return jsonRequest(`/opportunities/${id}`, payload, "PATCH");
}

export function attachManualDocumentUrl(id, url, label) {
  return jsonRequest(`/opportunities/${id}/documents/manual-url`, { url, label }, "POST");
}

export function getOpportunityDocuments(id) {
  return request(`/opportunities/${id}/documents`);
}

export function discoverOpportunityDocuments(id) {
  return request(`/opportunities/${id}/discover-documents`, { method: "POST" });
}

export function downloadOpportunityDocuments(id) {
  return request(`/opportunities/${id}/download-documents`, { method: "POST" });
}

export function parseOpportunityDocuments(id) {
  return request(`/opportunities/${id}/parse-documents`, { method: "POST" });
}

export function aiEvaluateOpportunity(id) {
  return request(`/opportunities/${id}/ai-evaluate`, { method: "POST" });
}

export function getOpportunityEvaluations(id) {
  return request(`/opportunities/${id}/evaluations`);
}

export function getOpportunityRequirements(id) {
  return request(`/opportunities/${id}/requirements`);
}

export function extractOpportunityRequirements(id) {
  return request(`/opportunities/${id}/extract-requirements`, { method: "POST" });
}

export function getSources() {
  return request("/sources");
}

export function scrapeSource(id) {
  return request(`/sources/${id}/scrape`, { method: "POST" });
}

export function previewSource(id) {
  return request(`/sources/${id}/preview`, { method: "POST" });
}

export function updateSource(id, payload) {
  return jsonRequest(`/sources/${id}`, payload, "PATCH");
}

export function getSourceAuthStatus(id) {
  return request(`/sources/${id}/auth-status`);
}

export function checkSourceAuthStatus(id) {
  return request(`/sources/${id}/auth-status/check`, { method: "POST" });
}

export function scrapeEnabledSources() {
  return request("/sources/scrape-enabled", { method: "POST" });
}

export function getSourceScraperCapabilities(id) {
  return request(`/sources/${id}/scraper-capabilities`);
}

export function seedSources() {
  return request("/sources/seed", { method: "POST" });
}
