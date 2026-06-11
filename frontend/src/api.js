export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return response.json();
}

export function getHealth() {
  return request("/health");
}

export function getOpportunities() {
  return request("/opportunities");
}

export function getOpportunity(id) {
  return request(`/opportunities/${id}`);
}

export function scoreOpportunity(id) {
  return request(`/opportunities/${id}/score`, { method: "POST" });
}

export function getOpportunityDocuments(id) {
  return request(`/opportunities/${id}/documents`);
}

export function downloadOpportunityDocuments(id) {
  return request(`/opportunities/${id}/download-documents`, { method: "POST" });
}

export function getSources() {
  return request("/sources");
}

export function scrapeSource(id) {
  return request(`/sources/${id}/scrape`, { method: "POST" });
}

export function scrapeEnabledSources() {
  return request("/sources/scrape-enabled", { method: "POST" });
}
