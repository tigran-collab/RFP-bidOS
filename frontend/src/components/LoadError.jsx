// Shared load-error surface: shows the real error message (api.js builds a
// detailed one) and, when a loader is provided, a Retry button that re-runs it.
export default function LoadError({ message, onRetry }) {
  return (
    <div className="load-error" role="alert">
      <p className="error-text">
        {message || "Failed to load data. Is the backend running?"}
      </p>
      {onRetry ? (
        <button className="secondary-button" type="button" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}
