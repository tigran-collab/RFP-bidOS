export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// --- Knowledge Base acting user (local-first; no login) ----
// The selected KB user id is stored client-side and sent as X-KB-User-Id so the
// backend can enforce role-based permissions. Defaults to the seeded admin.
const KB_USER_KEY = "kbUserId";

export function getKbUserId() {
  try {
    return localStorage.getItem(KB_USER_KEY) || null;
  } catch {
    return null;
  }
}

export function setKbUserId(id) {
  try {
    if (id === null || id === undefined || id === "") {
      localStorage.removeItem(KB_USER_KEY);
    } else {
      localStorage.setItem(KB_USER_KEY, String(id));
    }
  } catch {
    /* ignore storage errors */
  }
}

function kbHeaders(extra = {}) {
  const headers = { ...extra };
  const userId = getKbUserId();
  if (userId) {
    headers["X-KB-User-Id"] = userId;
  }
  return headers;
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    let detail = `API request failed: ${response.status}`;
    try {
      const payload = await response.json();
      if (Array.isArray(payload.detail)) {
        detail = payload.detail
          .map((item) => item?.msg || (typeof item === "string" ? item : JSON.stringify(item)))
          .join("; ");
      } else if (payload.detail && typeof payload.detail === "object") {
        detail = payload.detail.msg || JSON.stringify(payload.detail);
      } else {
        detail = payload.error || payload.detail || detail;
      }
    } catch {
      detail = `API request failed: ${response.status}`;
    }
    throw new Error(detail);
  }
  if (response.status === 204) {
    return null;
  }
  const text = await response.text();
  return text ? JSON.parse(text) : null;
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

export function getDashboardDigest(params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, value);
    }
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/dashboard/digest${suffix}`);
}

export function getAiStatus() {
  return request("/ai/status");
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

export function prioritizeAll() {
  return request("/opportunities/prioritize", { method: "POST" });
}

export function archivePastDeadlines() {
  return request("/opportunities/archive-past-deadlines", { method: "POST" });
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

export function deleteOpportunity(id) {
  return request(`/opportunities/${id}`, { method: "DELETE" });
}

export function attachManualDocumentUrl(id, url, label) {
  return jsonRequest(`/opportunities/${id}/documents/manual-url`, { url, label }, "POST");
}

export function getOpportunityDocuments(id) {
  return request(`/opportunities/${id}/documents`);
}

export function downloadOpportunityDocuments(id) {
  return request(`/opportunities/${id}/download-documents`, { method: "POST" });
}

export function downloadOpportunityPortalDocuments(id) {
  return request(`/opportunities/${id}/download-portal-documents`, { method: "POST" });
}

export function downloadDocument(id) {
  return request(`/documents/${id}/download`, { method: "POST" });
}

export function getDocumentFileUrl(id) {
  return `${API_BASE_URL}/documents/${id}/file`;
}

export function parseOpportunityDocuments(id) {
  return request(`/opportunities/${id}/parse-documents`, { method: "POST" });
}

export function aiEvaluateOpportunity(id) {
  return request(`/opportunities/${id}/ai-evaluate`, { method: "POST" });
}

export function generateAiSummary(id) {
  return request(`/opportunities/${id}/ai-summary`, { method: "POST" });
}

export function analyzeOpportunityDocuments(id, refresh = false) {
  const suffix = refresh ? "?refresh=true" : "";
  return request(`/opportunities/${id}/analyze-documents${suffix}`, { method: "POST" });
}

export function getDocumentBrief(id) {
  return request(`/opportunities/${id}/document-brief`);
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

export function scrapeEnabledSources() {
  return request("/sources/scrape-enabled", { method: "POST" });
}

export function seedSources() {
  return request("/sources/seed", { method: "POST" });
}

// ---- Portals (in-app authenticated portal management) ----
export function getPortalTemplates() {
  return request("/sources/portal-templates");
}

export function addPortal(payload) {
  return jsonRequest("/sources/add-portal", payload, "POST");
}

export function setSourceCredentials(id, { username, password }) {
  return jsonRequest(`/sources/${id}/credentials`, { username, password }, "PUT");
}

export function deleteSourceCredentials(id) {
  return request(`/sources/${id}/credentials`, { method: "DELETE" });
}

export function startPortalLogin(id) {
  return request(`/sources/${id}/portal-login`, { method: "POST" });
}

export function getLoginStatus(id) {
  return request(`/sources/${id}/login-status`);
}

export function setSourceEnabled(id, enabled) {
  return updateSource(id, { enabled });
}

// ---- Notion connector ----
export function getNotionStatus() {
  return request("/notion/status");
}

export function saveNotionConfig({ token, database_id }) {
  return jsonRequest("/notion/config", { token, database_id }, "PUT");
}

export function deleteNotionConfig() {
  return request("/notion/config", { method: "DELETE" });
}

export function syncNotion(body = {}) {
  return jsonRequest("/notion/sync", body, "POST");
}

// ============================================================================
// Company Knowledge Base
// ============================================================================

function kbGet(path, params = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      query.append(key, value);
    }
  });
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return request(`/kb${path}${suffix}`, { headers: kbHeaders() });
}

function kbSend(path, payload, method = "POST") {
  return request(`/kb${path}`, {
    method,
    headers: kbHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload || {}),
  });
}

function kbPost(path) {
  return request(`/kb${path}`, { method: "POST", headers: kbHeaders() });
}

// ---- meta / identity ----
export function getKbMeta() {
  return kbGet("/meta");
}
export function getKbWhoami() {
  return kbGet("/whoami");
}

// ---- users / entities ----
export function getKbUsers() {
  return kbGet("/users");
}
export function createKbUser(payload) {
  return kbSend("/users", payload, "POST");
}
export function updateKbUser(id, payload) {
  return kbSend(`/users/${id}`, payload, "PATCH");
}
export function getKbEntities() {
  return kbGet("/entities");
}
export function createKbEntity(payload) {
  return kbSend("/entities", payload, "POST");
}
export function updateKbEntity(id, payload) {
  return kbSend(`/entities/${id}`, payload, "PATCH");
}

// ---- dashboard ----
export function getKbDashboard(params = {}) {
  return kbGet("/dashboard", params);
}

// ---- documents ----
export function getKbDocuments(params = {}) {
  return kbGet("/documents", params);
}
export function uploadKbDocuments(formData) {
  return request("/kb/documents", {
    method: "POST",
    headers: kbHeaders(),
    body: formData,
  });
}
export function getKbDocument(id) {
  return kbGet(`/documents/${id}`);
}
export function updateKbDocument(id, payload) {
  return kbSend(`/documents/${id}`, payload, "PATCH");
}
export function processKbDocument(id) {
  return kbPost(`/documents/${id}/process`);
}
export function archiveKbDocument(id, archived = true) {
  return kbSend(`/documents/${id}/archive`, { archived }, "POST");
}
export function deleteKbDocument(id) {
  return request(`/kb/documents/${id}`, { method: "DELETE", headers: kbHeaders() });
}
export function kbDocumentFileUrl(id) {
  return `${API_BASE_URL}/kb/documents/${id}/file`;
}

// ---- gallery ----
export function getKbGallery(params = {}) {
  return kbGet("/gallery", params);
}
export function uploadKbGallery(formData) {
  return request("/kb/gallery", {
    method: "POST",
    headers: kbHeaders(),
    body: formData,
  });
}
export function updateKbGalleryAsset(id, payload) {
  return kbSend(`/gallery/${id}`, payload, "PATCH");
}
export function archiveKbGalleryAsset(id, archived = true) {
  return kbSend(`/gallery/${id}/archive`, { archived }, "POST");
}
export function deleteKbGalleryAsset(id) {
  return request(`/kb/gallery/${id}`, { method: "DELETE", headers: kbHeaders() });
}
export function kbGalleryFileUrl(id) {
  return `${API_BASE_URL}/kb/gallery/${id}/file`;
}

// ---- claims ----
export function getKbClaims(params = {}) {
  return kbGet("/claims", params);
}
export function createKbClaim(payload) {
  return kbSend("/claims", payload, "POST");
}
export function getKbClaim(id) {
  return kbGet(`/claims/${id}`);
}
export function updateKbClaim(id, payload) {
  return kbSend(`/claims/${id}`, payload, "PATCH");
}
export function claimAction(id, action, note) {
  return kbSend(`/claims/${id}/${action}`, { note }, "POST");
}
export function supersedeKbClaim(id, supersededById, note) {
  return kbSend(`/claims/${id}/supersede`, { superseded_by_id: supersededById, note }, "POST");
}
export function addKbClaimSource(id, payload) {
  return kbSend(`/claims/${id}/sources`, payload, "POST");
}
export function restoreKbClaimVersion(id, versionId) {
  return kbPost(`/claims/${id}/restore/${versionId}`);
}
export function expireKbClaims() {
  return kbPost("/claims/expire");
}

// ---- questions / answers ----
export function getKbQuestions(params = {}) {
  return kbGet("/questions", params);
}
export function createKbQuestion(payload) {
  return kbSend("/questions", payload, "POST");
}
export function getKbAnswers(params = {}) {
  return kbGet("/answers", params);
}
export function createKbAnswer(payload) {
  return kbSend("/answers", payload, "POST");
}
export function getKbAnswer(id) {
  return kbGet(`/answers/${id}`);
}
export function updateKbAnswer(id, payload) {
  return kbSend(`/answers/${id}`, payload, "PATCH");
}
export function answerAction(id, action, note) {
  return kbSend(`/answers/${id}/${action}`, { note }, "POST");
}

// ---- responses / drafting ----
export function generateKbResponse(payload) {
  return kbSend("/responses/generate", payload, "POST");
}
export function getKbResponses(params = {}) {
  return kbGet("/responses", params);
}
export function getKbResponse(id) {
  return kbGet(`/responses/${id}`);
}
export function updateKbResponse(id, payload) {
  return kbSend(`/responses/${id}`, payload, "PATCH");
}
export function transformKbResponse(id, operation, instructions, provider) {
  return kbSend(`/responses/${id}/transform`, { operation, instructions, provider }, "POST");
}

// ---- AI drafting provider config ----
export function getKbAiConfig() {
  return kbGet("/ai-config");
}
export function saveKbClaudeConfig({ api_key, model }) {
  return kbSend("/ai-config/claude", { api_key, model }, "PUT");
}
export function deleteKbClaudeConfig() {
  return request("/kb/ai-config/claude", { method: "DELETE", headers: kbHeaders() });
}

// ---- Google Drive import ----
export function getKbDriveStatus() {
  return kbGet("/google-drive/status");
}
export function saveKbDriveConfig(payload) {
  return kbSend("/google-drive/config", payload, "PUT");
}
export function deleteKbDriveConfig() {
  return request("/kb/google-drive/config", { method: "DELETE", headers: kbHeaders() });
}
export function getKbDriveFiles(folderId) {
  return kbGet("/google-drive/files", folderId ? { folder_id: folderId } : {});
}
export function importKbDriveFiles(fileIds, companyEntityId) {
  return kbSend("/google-drive/import", { file_ids: fileIds, company_entity_id: companyEntityId }, "POST");
}
export function saveKbResponseToProject(id, payload) {
  return kbSend(`/responses/${id}/save-to-project`, payload, "POST");
}
export function deleteKbResponse(id) {
  return request(`/kb/responses/${id}`, { method: "DELETE", headers: kbHeaders() });
}

// ---- conflicts ----
export function getKbConflicts(params = {}) {
  return kbGet("/conflicts", params);
}
export function detectKbConflicts(companyEntityId) {
  return kbSend("/conflicts/detect", { company_entity_id: companyEntityId }, "POST");
}
export function resolveKbConflict(id, payload) {
  return kbSend(`/conflicts/${id}/resolve`, payload, "POST");
}
export function dismissKbConflict(id, note) {
  return kbSend(`/conflicts/${id}/dismiss`, { note }, "POST");
}

// ---- reviews / comments / approvals / audit ----
export function getKbReviewRequests(params = {}) {
  return kbGet("/review-requests", params);
}
export function createKbReviewRequest(payload) {
  return kbSend("/review-requests", payload, "POST");
}
export function resolveKbReviewRequest(id, payload) {
  return kbSend(`/review-requests/${id}/resolve`, payload, "POST");
}
export function getKbComments(targetType, targetId) {
  return kbGet("/comments", { target_type: targetType, target_id: targetId });
}
export function addKbComment(payload) {
  return kbSend("/comments", payload, "POST");
}
export function getKbApprovals(targetType, targetId) {
  return kbGet("/approvals", { target_type: targetType, target_id: targetId });
}
export function getKbAudit(params = {}) {
  return kbGet("/audit", params);
}

// ---- search ----
export function kbSearch(params = {}) {
  return kbGet("/search", params);
}
