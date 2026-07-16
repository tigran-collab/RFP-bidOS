import { expireKbClaims, getKbDashboard } from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, useAsync, formatDate } from "./KbShared.jsx";
import { useState } from "react";

export default function ExpirationQueue({ onNavigate }) {
  const { data, loading, error, reload } = useAsync(() => getKbDashboard(), []);
  const [msg, setMsg] = useState("");

  async function sweep() {
    try {
      const r = await expireKbClaims();
      setMsg(`Marked ${r.expired} claim(s) as expired.`);
      reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const items = data?.expiring_items || [];
  const expired = items.filter((i) => i.expired);
  const soon = items.filter((i) => !i.expired);

  function open(item) {
    if (item.kind === "document") onNavigate("kbDocumentDetail", { id: item.id });
    else onNavigate("kbClaimDetail", { id: item.id });
  }

  return (
    <KbPage
      current="kbExpirations"
      onNavigate={onNavigate}
      onUserChange={reload}
      title="Expiration Queue"
      actions={
        <button className="secondary-button" type="button" onClick={sweep}>Run Expiration Sweep</button>
      }
    >
      {msg ? <p className="notice-text">{msg}</p> : null}
      {error ? (
        <LoadError message={error} onRetry={reload} />
      ) : loading ? (
        <p>Loading...</p>
      ) : (
        <>
          <h2>Expired ({expired.length})</h2>
          <ExpTable items={expired} onOpen={open} />
          <h2>Expiring Soon ({soon.length})</h2>
          <ExpTable items={soon} onOpen={open} />
        </>
      )}
    </KbPage>
  );
}

function ExpTable({ items, onOpen }) {
  if (!items.length) return <p className="muted-text">None.</p>;
  return (
    <table className="data-table">
      <thead>
        <tr><th>Item</th><th>Kind</th><th>Category</th><th>Expiration</th></tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={`${item.kind}-${item.id}`}>
            <td><button className="link-button" type="button" onClick={() => onOpen(item)}>{item.title}</button></td>
            <td>{item.kind}</td>
            <td>{item.category || ""}</td>
            <td>{formatDate(item.expiration_date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
