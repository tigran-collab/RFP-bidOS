export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path) {
  const response = await fetch(`${API_BASE_URL}${path}`);
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

export function getSources() {
  return request("/sources");
}
