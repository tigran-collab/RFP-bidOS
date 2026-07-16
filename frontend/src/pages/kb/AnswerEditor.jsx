import { useState } from "react";

import {
  answerAction,
  createKbAnswer,
  getKbAnswer,
  getKbEntities,
  updateKbAnswer,
} from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, StatusBadge, useAsync, useKbMeta } from "./KbShared.jsx";

const BLANK = {
  question_title: "",
  category: "",
  short_answer: "",
  standard_answer: "",
  long_answer: "",
  company_entity_id: "",
  internal_guidance: "",
  restrictions: "",
};

export default function AnswerEditor({ params, onNavigate }) {
  const id = params?.id;
  const meta = useKbMeta();
  const entities = useAsync(() => getKbEntities(), []);
  const existing = useAsync(() => (id ? getKbAnswer(id) : Promise.resolve(null)), [id]);
  const [form, setForm] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState("");

  // Initialize form from loaded answer or blank.
  const answer = existing.data?.answer;
  if (form === null && !existing.loading) {
    setForm(answer ? { ...BLANK, ...answer, company_entity_id: answer.company_entity_id || "" } : { ...BLANK });
  }

  function set(key, value) {
    setForm({ ...form, [key]: value });
  }

  async function save() {
    setBusy("save");
    setMsg("");
    try {
      const payload = { ...form };
      if (!payload.company_entity_id) delete payload.company_entity_id;
      if (id) {
        await updateKbAnswer(id, payload);
        setMsg("Saved.");
        existing.reload();
      } else {
        const created = await createKbAnswer(payload);
        onNavigate("kbAnswerEditor", { id: created.id });
      }
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy("");
    }
  }

  async function act(action) {
    setBusy(action);
    try {
      await answerAction(id, action, action === "reject" ? window.prompt("Reason?") || "" : undefined);
      existing.reload();
    } catch (err) {
      setMsg(err.message);
    } finally {
      setBusy("");
    }
  }

  if (existing.error) {
    return (
      <KbPage current="kbAnswerEditor" onNavigate={onNavigate} onUserChange={existing.reload} title="Answer">
        <LoadError message={existing.error} onRetry={existing.reload} />
      </KbPage>
    );
  }
  if (!form) {
    return (
      <KbPage current="kbAnswerEditor" onNavigate={onNavigate} onUserChange={() => {}} title="Answer">
        <p>Loading...</p>
      </KbPage>
    );
  }

  return (
    <KbPage
      current="kbAnswerEditor"
      onNavigate={onNavigate}
      onUserChange={() => existing.reload()}
      title={id ? "Edit Answer" : "New Answer"}
      actions={
        <>
          <button className="secondary-button" type="button" onClick={() => onNavigate("kbAnswers")}>← Library</button>
          {answer ? <StatusBadge status={answer.status} /> : null}
          {id ? (
            <>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("approve")}>Approve</button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("reject")}>Reject</button>
              <button className="secondary-button" type="button" disabled={busy} onClick={() => act("archive")}>Archive</button>
            </>
          ) : null}
        </>
      }
    >
      {msg ? <p className="notice-text">{msg}</p> : null}
      <div className="kb-card">
        <div className="kb-form-grid">
          <label className="kb-field kb-field--full">Question Title<input value={form.question_title} onChange={(e) => set("question_title", e.target.value)} /></label>
          <label className="kb-field">Category
            <select value={form.category || ""} onChange={(e) => set("category", e.target.value)}>
              <option value="">—</option>
              {(meta?.answer_categories || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="kb-field">Company Entity
            <select value={form.company_entity_id || ""} onChange={(e) => set("company_entity_id", e.target.value)}>
              <option value="">—</option>
              {(entities.data || []).map((ent) => <option key={ent.id} value={ent.id}>{ent.name}</option>)}
            </select>
          </label>
        </div>
        <label className="kb-field kb-field--full">Short Answer<textarea rows={2} value={form.short_answer || ""} onChange={(e) => set("short_answer", e.target.value)} /></label>
        <label className="kb-field kb-field--full">Standard Answer<textarea rows={4} value={form.standard_answer || ""} onChange={(e) => set("standard_answer", e.target.value)} /></label>
        <label className="kb-field kb-field--full">Long Answer<textarea rows={6} value={form.long_answer || ""} onChange={(e) => set("long_answer", e.target.value)} /></label>
        <label className="kb-field kb-field--full">Internal Guidance<input value={form.internal_guidance || ""} onChange={(e) => set("internal_guidance", e.target.value)} /></label>
        <label className="kb-field kb-field--full">Restrictions<input value={form.restrictions || ""} onChange={(e) => set("restrictions", e.target.value)} /></label>
        <button className="primary-button" type="button" onClick={save} disabled={busy || !form.question_title}>
          {busy === "save" ? "Saving..." : id ? "Save Changes" : "Create Answer"}
        </button>
      </div>
    </KbPage>
  );
}
