import { useState } from "react";

import {
  createKbEntity,
  createKbUser,
  deleteKbClaudeConfig,
  deleteKbDriveConfig,
  getKbAiConfig,
  getKbAudit,
  getKbDriveStatus,
  getKbEntities,
  getKbUsers,
  saveKbClaudeConfig,
  saveKbDriveConfig,
  updateKbUser,
} from "../../api.js";
import LoadError from "../../components/LoadError.jsx";
import { KbPage, useAsync, useKbMeta, formatDate } from "./KbShared.jsx";

export default function KbAdminSettings({ onNavigate }) {
  const meta = useKbMeta();
  const users = useAsync(() => getKbUsers(), []);
  const entities = useAsync(() => getKbEntities(), []);
  const audit = useAsync(() => getKbAudit({ limit: 50 }), []);
  const aiConfig = useAsync(() => getKbAiConfig(), []);
  const driveConfig = useAsync(() => getKbDriveStatus(), []);
  const [newUser, setNewUser] = useState({ name: "", email: "", role: "read_only" });
  const [newEntity, setNewEntity] = useState({ name: "" });
  const [claudeForm, setClaudeForm] = useState({ api_key: "", model: "claude-opus-4-8" });
  const [driveForm, setDriveForm] = useState({
    access_token: "", folder_id: "", refresh_token: "", client_id: "", client_secret: "",
  });
  const [msg, setMsg] = useState("");

  async function saveDrive() {
    try {
      const payload = { folder_id: driveForm.folder_id };
      ["access_token", "refresh_token", "client_id", "client_secret"].forEach((k) => {
        if (driveForm[k]) payload[k] = driveForm[k];
      });
      await saveKbDriveConfig(payload);
      setDriveForm({ ...driveForm, access_token: "", refresh_token: "", client_secret: "" });
      driveConfig.reload();
      setMsg("Google Drive configuration saved.");
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function removeDrive() {
    if (!window.confirm("Remove the stored Google Drive credentials?")) return;
    try {
      await deleteKbDriveConfig();
      driveConfig.reload();
      setMsg("Google Drive credentials removed.");
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function saveClaude() {
    try {
      const payload = { model: claudeForm.model };
      if (claudeForm.api_key) payload.api_key = claudeForm.api_key;
      await saveKbClaudeConfig(payload);
      setClaudeForm({ ...claudeForm, api_key: "" });
      aiConfig.reload();
      setMsg("Claude API configuration saved.");
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function removeClaude() {
    if (!window.confirm("Remove the stored Claude API key?")) return;
    try {
      await deleteKbClaudeConfig();
      aiConfig.reload();
      setMsg("Claude API key removed.");
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function addUser() {
    try {
      await createKbUser(newUser);
      setNewUser({ name: "", email: "", role: "read_only" });
      users.reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function changeRole(user, role) {
    try {
      await updateKbUser(user.id, { role });
      users.reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function toggleActive(user) {
    try {
      await updateKbUser(user.id, { active: !user.active });
      users.reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  async function addEntity() {
    try {
      await createKbEntity(newEntity);
      setNewEntity({ name: "" });
      entities.reload();
    } catch (err) {
      setMsg(err.message);
    }
  }

  const reloadAll = () => {
    users.reload();
    entities.reload();
    audit.reload();
    aiConfig.reload();
    driveConfig.reload();
  };

  return (
    <KbPage current="kbAdmin" onNavigate={onNavigate} onUserChange={reloadAll} title="Admin Settings">
      {msg ? <p className="error-text">{msg}</p> : null}

      <h2>Users & Roles</h2>
      <div className="kb-card">
        <div className="kb-form-grid">
          <label className="kb-field">Name<input value={newUser.name} onChange={(e) => setNewUser({ ...newUser, name: e.target.value })} /></label>
          <label className="kb-field">Email<input value={newUser.email} onChange={(e) => setNewUser({ ...newUser, email: e.target.value })} /></label>
          <label className="kb-field">Role
            <select value={newUser.role} onChange={(e) => setNewUser({ ...newUser, role: e.target.value })}>
              {(meta?.roles || []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </label>
        </div>
        <button className="primary-button" type="button" onClick={addUser} disabled={!newUser.name}>Add User</button>
      </div>
      {users.error ? (
        <LoadError message={users.error} onRetry={users.reload} />
      ) : (
        <table className="data-table">
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Active</th><th></th></tr></thead>
          <tbody>
            {(users.data || []).map((u) => (
              <tr key={u.id}>
                <td>{u.name}</td>
                <td>{u.email || ""}</td>
                <td>
                  <select value={u.role} onChange={(e) => changeRole(u, e.target.value)}>
                    {(meta?.roles || []).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                  </select>
                </td>
                <td>{u.active ? "Yes" : "No"}</td>
                <td><button className="link-button" type="button" onClick={() => toggleActive(u)}>{u.active ? "Deactivate" : "Activate"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Company Entities</h2>
      <div className="kb-card">
        <div className="kb-form-grid">
          <label className="kb-field kb-field--full">Entity Name<input value={newEntity.name} onChange={(e) => setNewEntity({ ...newEntity, name: e.target.value })} /></label>
        </div>
        <button className="primary-button" type="button" onClick={addEntity} disabled={!newEntity.name}>Add Entity</button>
      </div>
      <table className="data-table">
        <thead><tr><th>Name</th><th>Legal Name</th><th>State</th><th>Active</th></tr></thead>
        <tbody>
          {(entities.data || []).map((e) => (
            <tr key={e.id}>
              <td>{e.name}</td>
              <td>{e.legal_name || ""}</td>
              <td>{e.state_of_incorporation || ""}</td>
              <td>{e.active ? "Yes" : "No"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>AI Drafting Provider</h2>
      <div className="kb-card">
        <p className="muted-text">
          The Response Workspace drafts with the local Ollama model by default.
          Optionally configure Anthropic's Claude API as a cloud provider for
          higher-quality drafts. The API key is stored only in the OS keychain —
          never in the database, logs, or any API response. Retrieved company
          context is sent to the cloud when the Claude provider is used.
        </p>
        {aiConfig.data ? (
          <p className="muted-text">
            Local (Ollama): <strong>{aiConfig.data.local?.available ? "Available" : "Unavailable"}</strong>
            {" · "}Claude API:{" "}
            <strong>
              {aiConfig.data.claude?.configured
                ? `Configured (${aiConfig.data.claude.model})`
                : "Not configured"}
            </strong>
            {aiConfig.data.claude && !aiConfig.data.claude.keychain_available
              ? " — OS keychain unavailable on this machine"
              : ""}
          </p>
        ) : null}
        <div className="kb-form-grid">
          <label className="kb-field">
            Claude API Key
            <input
              type="password"
              placeholder={aiConfig.data?.claude?.configured ? "•••••• (leave blank to keep)" : "sk-ant-..."}
              value={claudeForm.api_key}
              onChange={(e) => setClaudeForm({ ...claudeForm, api_key: e.target.value })}
            />
          </label>
          <label className="kb-field">
            Model
            <input
              value={claudeForm.model}
              onChange={(e) => setClaudeForm({ ...claudeForm, model: e.target.value })}
            />
          </label>
        </div>
        <div className="button-row">
          <button className="primary-button" type="button" onClick={saveClaude} disabled={!claudeForm.api_key && !aiConfig.data?.claude?.configured}>
            Save Claude Config
          </button>
          {aiConfig.data?.claude?.configured ? (
            <button className="danger-button" type="button" onClick={removeClaude}>Remove Key</button>
          ) : null}
        </div>
      </div>

      <h2>Google Drive Import</h2>
      <div className="kb-card">
        <p className="muted-text">
          Import company documents from Google Drive into the vault. This app
          can't run Google's sign-in itself — obtain an OAuth access token (and,
          for auto-refresh, a refresh token + client id/secret) and paste them
          here. Credentials are stored only in the OS keychain, never in the
          database or any API response.
        </p>
        {driveConfig.data ? (
          <p className="muted-text">
            Status:{" "}
            <strong>
              {driveConfig.data.configured
                ? `Connected${driveConfig.data.folder_id ? ` (folder ${driveConfig.data.folder_id})` : ""}`
                : "Not configured"}
            </strong>
            {driveConfig.data.configured
              ? ` · auto-refresh: ${driveConfig.data.has_refresh ? "on" : "off"}`
              : ""}
          </p>
        ) : null}
        <div className="kb-form-grid">
          <label className="kb-field">
            OAuth Access Token
            <input
              type="password"
              placeholder={driveConfig.data?.configured ? "•••••• (leave blank to keep)" : "ya29...."}
              value={driveForm.access_token}
              onChange={(e) => setDriveForm({ ...driveForm, access_token: e.target.value })}
            />
          </label>
          <label className="kb-field">
            Folder ID (optional)
            <input value={driveForm.folder_id} onChange={(e) => setDriveForm({ ...driveForm, folder_id: e.target.value })} />
          </label>
          <label className="kb-field">
            Refresh Token (optional)
            <input type="password" value={driveForm.refresh_token} onChange={(e) => setDriveForm({ ...driveForm, refresh_token: e.target.value })} />
          </label>
          <label className="kb-field">
            OAuth Client ID (optional)
            <input value={driveForm.client_id} onChange={(e) => setDriveForm({ ...driveForm, client_id: e.target.value })} />
          </label>
          <label className="kb-field">
            OAuth Client Secret (optional)
            <input type="password" value={driveForm.client_secret} onChange={(e) => setDriveForm({ ...driveForm, client_secret: e.target.value })} />
          </label>
        </div>
        <div className="button-row">
          <button className="primary-button" type="button" onClick={saveDrive} disabled={!driveForm.access_token && !driveConfig.data?.configured}>
            Save Drive Config
          </button>
          {driveConfig.data?.configured ? (
            <button className="danger-button" type="button" onClick={removeDrive}>Disconnect</button>
          ) : null}
        </div>
      </div>

      <h2>Audit Log (recent)</h2>
      {audit.error ? (
        <LoadError message={audit.error} onRetry={audit.reload} />
      ) : (
        <table className="data-table">
          <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th></tr></thead>
          <tbody>
            {(audit.data || []).map((a) => (
              <tr key={a.id}>
                <td>{formatDate(a.created_at)}</td>
                <td>{a.actor_id ?? "system"}</td>
                <td>{a.action}</td>
                <td>{a.target_type ? `${a.target_type} #${a.target_id}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </KbPage>
  );
}
