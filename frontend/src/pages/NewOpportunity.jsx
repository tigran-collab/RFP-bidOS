import { useState } from "react";

import { createOpportunity } from "../api.js";
import OpportunityFields, {
  buildOpportunityPayload,
} from "../components/OpportunityFields.jsx";

const EMPTY = {
  title: "",
  review_status: "New",
  pre_bid_mandatory: false,
};

export default function NewOpportunity({ onOpenOpportunity }) {
  const [values, setValues] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function onChange(field, value) {
    setValues((current) => ({ ...current, [field]: value }));
  }

  async function submit(event) {
    event.preventDefault();
    if (!values.title.trim()) {
      setError("Title is required.");
      return;
    }
    try {
      setSaving(true);
      const payload = buildOpportunityPayload(values);
      const created = await createOpportunity(payload);
      setError("");
      if (onOpenOpportunity) {
        onOpenOpportunity(created.id);
      }
    } catch (err) {
      setError(err.message || "Failed to create opportunity.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section>
      <h1>New Opportunity</h1>
      <p className="muted-text">
        Use manual entry for BidNet, PlanetBids, emails, PDFs, screenshots, and
        portals that do not scrape cleanly.
      </p>
      {error ? <p className="error-text">{error}</p> : null}
      <form onSubmit={submit}>
        <OpportunityFields values={values} onChange={onChange} />
        <div className="page-actions">
          <button className="primary-button" type="submit" disabled={saving}>
            {saving ? "Creating..." : "Create Opportunity"}
          </button>
        </div>
      </form>
    </section>
  );
}
