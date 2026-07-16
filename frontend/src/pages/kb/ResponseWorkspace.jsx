import { useState } from "react";

import {
  generateKbResponse,
  getKbEntities,
  saveKbResponseToProject,
  transformKbResponse,
  updateKbResponse,
} from "../../api.js";
import { KbPage, Warnings, useAsync, useKbMeta } from "./KbShared.jsx";

const EMPTY = {
  question: "",
  agency_name: "",
  solicitation_number: "",
  company_entity_id: "",
  state: "",
  industry: "",
  service_type: "",
  word_count_target: "",
  tone: "Professional",
  detail_level: "Standard",
  formatting_instructions: "",
  provider: "local",
};

const TRANSFORMS = [
  ["shorten", "Shorten"],
  ["expand", "Expand"],
  ["formal", "More Formal"],
  ["bullets", "To Bullets"],
  ["narrative", "To Narrative"],
  ["regenerate", "Regenerate"],
];

export default function ResponseWorkspace({ onNavigate }) {
  const meta = useKbMeta();
  const entities = useAsync(() => getKbEntities(), []);
  const [form, setForm] = useState(EMPTY);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  function set(key, value) {
    setForm({ ...form, [key]: value });
  }

  async function generate() {
    setBusy("generate");
    setError("");
    setResult(null);
    try {
      const payload = { ...form };
      Object.keys(payload).forEach((k) => {
        if (payload[k] === "" || payload[k] === null) delete payload[k];
      });
      if (payload.word_count_target) payload.word_count_target = Number(payload.word_count_target);
      if (payload.company_entity_id) payload.company_entity_id = Number(payload.company_entity_id);
      const res = await generateKbResponse(payload);
      setResult(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function transform(op) {
    if (!result?.response?.id) return;
    setBusy(op);
    setError("");
    try {
      const res = await transformKbResponse(result.response.id, op, undefined, form.provider);
      // regenerate returns full shape; transforms return {response, warnings}
      setResult((prev) => ({
        ...prev,
        response: res.response,
        warnings: res.warnings || prev.warnings,
        citations: res.citations || prev.citations,
      }));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy("");
    }
  }

  async function saveText(newText) {
    if (!result?.response?.id) return;
    try {
      const updated = await updateKbResponse(result.response.id, { response_text: newText });
      setResult((prev) => ({ ...prev, response: updated }));
    } catch (err) {
      setError(err.message);
    }
  }

  async function saveToProject() {
    const opp = window.prompt("Opportunity ID to save this response under:");
    if (!opp) return;
    try {
      await saveKbResponseToProject(result.response.id, { opportunity_id: Number(opp) });
      alert("Saved to opportunity " + opp);
    } catch (err) {
      setError(err.message);
    }
  }

  function copy() {
    navigator.clipboard?.writeText(result?.response?.response_text || "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const response = result?.response;

  return (
    <KbPage current="kbWorkspace" onNavigate={onNavigate} onUserChange={() => {}} title="AI Response Workspace">
      <div className="kb-card">
        <label className="kb-field kb-field--full">
          RFP Question(s)
          <textarea rows={3} value={form.question} placeholder="Paste an RFP question or drafting request..." onChange={(e) => set("question", e.target.value)} />
        </label>
        <div className="kb-form-grid">
          <label className="kb-field">Agency<input value={form.agency_name} onChange={(e) => set("agency_name", e.target.value)} /></label>
          <label className="kb-field">Solicitation #<input value={form.solicitation_number} onChange={(e) => set("solicitation_number", e.target.value)} /></label>
          <label className="kb-field">Company Entity
            <select value={form.company_entity_id} onChange={(e) => set("company_entity_id", e.target.value)}>
              <option value="">—</option>
              {(entities.data || []).map((ent) => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
            </select>
          </label>
          <label className="kb-field">State
            <select value={form.state} onChange={(e) => set("state", e.target.value)}>
              <option value="">—</option>
              {(meta?.states || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="kb-field">Service Type
            <select value={form.service_type} onChange={(e) => set("service_type", e.target.value)}>
              <option value="">—</option>
              {(meta?.service_types || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="kb-field">Industry
            <select value={form.industry} onChange={(e) => set("industry", e.target.value)}>
              <option value="">—</option>
              {(meta?.industries || []).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="kb-field">Tone
            <select value={form.tone} onChange={(e) => set("tone", e.target.value)}>
              {(meta?.tones || ["Professional"]).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="kb-field">Detail
            <select value={form.detail_level} onChange={(e) => set("detail_level", e.target.value)}>
              {(meta?.detail_levels || ["Standard"]).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="kb-field">Word Count<input type="number" value={form.word_count_target} onChange={(e) => set("word_count_target", e.target.value)} /></label>
          <label className="kb-field">AI Provider
            <select value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              {(meta?.ai_providers || [{ value: "local", label: "Local (Ollama)" }]).map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
          </label>
          <label className="kb-field kb-field--full">Formatting Instructions<input value={form.formatting_instructions} onChange={(e) => set("formatting_instructions", e.target.value)} /></label>
        </div>
        <button className="primary-button" type="button" onClick={generate} disabled={busy === "generate" || !form.question.trim()}>
          {busy === "generate" ? "Generating..." : "Generate Response"}
        </button>
        {error ? <p className="error-text" style={{ marginTop: "0.5rem" }}>{error}</p> : null}
      </div>

      {response ? (
        <div className="kb-two-col">
          <div>
            <h2>
              Drafted Response{" "}
              <span className="kb-confidence" title="Confidence score">
                {response.confidence_score != null ? Math.round(response.confidence_score * 100) + "%" : ""}
              </span>
            </h2>
            <div className="kb-inline-actions" style={{ marginBottom: "0.75rem" }}>
              {TRANSFORMS.map(([op, label]) => (
                <button key={op} className="secondary-button" type="button" disabled={busy} onClick={() => transform(op)}>
                  {busy === op ? "..." : label}
                </button>
              ))}
              <button className="secondary-button" type="button" onClick={copy}>{copied ? "Copied!" : "Copy"}</button>
              <button className="secondary-button" type="button" onClick={saveToProject}>Save to Project</button>
            </div>
            <textarea
              className="kb-response-text"
              style={{ width: "100%", minHeight: "16rem" }}
              value={response.response_text || ""}
              onChange={(e) => setResult((p) => ({ ...p, response: { ...p.response, response_text: e.target.value } }))}
              onBlur={(e) => saveText(e.target.value)}
            />
          </div>
          <div>
            <h2>Warnings</h2>
            <Warnings warnings={result.warnings} />
            <h2>Sources & Citations</h2>
            {!(result.sources || []).length ? (
              <p className="muted-text">No sources.</p>
            ) : (
              (result.sources || []).map((s) => (
                <div className="kb-citation" key={`${s.kind}-${s.id}`}>
                  <span className="kb-citation-marker">{s.marker}</span>
                  <strong>{s.kind}</strong> — {s.title}
                  {s.document_id ? (
                    <button className="link-button" type="button" style={{ marginLeft: "0.5rem" }}
                      onClick={() => onNavigate("kbDocumentDetail", { id: s.document_id })}>
                      open doc{s.page_number ? ` p.${s.page_number}` : ""}
                    </button>
                  ) : null}
                  <div className="muted-text">{(s.excerpt || s.text || "").slice(0, 220)}</div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </KbPage>
  );
}
