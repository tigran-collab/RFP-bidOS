// Map a status string to a color variant so badges read at a glance.
const SUCCESS = ["bid", "pursue", "passed", "relevant", "low", "available", "completed", "downloaded", "parsed", "verified", "active", "open"];
const DANGER = ["no bid", "do not pursue", "failed", "past due", "disqualifying", "high", "unavailable", "error", "missing", "not relevant"];
const WARN = ["needs review", "watchlist", "maybe", "medium", "pending", "needs action", "review"];
const INFO = ["new", "identified", "assigned", "addressed", "archived"];

function variantFor(status) {
  const value = String(status || "").trim().toLowerCase();
  // "Parsed (No Text)" contains "parsed" (success) but means an unreadable doc —
  // flag it as a caution, not a green success.
  if (value.includes("no text")) return "status-badge--warn";
  if (DANGER.some((k) => value.includes(k))) return "status-badge--danger";
  if (SUCCESS.some((k) => value === k || value.includes(k))) return "status-badge--success";
  if (WARN.some((k) => value.includes(k))) return "status-badge--warn";
  if (INFO.some((k) => value.includes(k))) return "status-badge--info";
  return "";
}

export default function StatusBadge({ status }) {
  return <span className={`status-badge ${variantFor(status)}`.trim()}>{status}</span>;
}
