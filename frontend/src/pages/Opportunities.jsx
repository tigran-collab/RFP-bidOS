import { useEffect, useState } from "react";

import { getOpportunities } from "../api.js";
import OpportunityTable from "../components/OpportunityTable.jsx";

const errorMessage = "Failed to load backend data. Is the backend running?";

export default function Opportunities({ onOpenOpportunity }) {
  const [opportunities, setOpportunities] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadOpportunities() {
      try {
        setLoading(true);
        setOpportunities(await getOpportunities());
        setError("");
      } catch {
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    }

    loadOpportunities();
  }, []);

  if (loading) {
    return <p>Loading...</p>;
  }

  if (error) {
    return <p className="error-text">{error}</p>;
  }

  return (
    <section>
      <h1>Opportunities</h1>
      <OpportunityTable
        opportunities={opportunities}
        onOpenOpportunity={onOpenOpportunity}
      />
    </section>
  );
}
