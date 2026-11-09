import { useEffect, useState } from "react";
import type { AgentActivityEvent } from "../types";

type Props = {
  apiUrl: string;
  theme: "dark" | "light";
  onToggleTheme: () => void;
};

export default function SettingsView({ apiUrl, theme, onToggleTheme }: Props) {
  const [models, setModels] = useState<string[]>([]);
  const [currentModel, setCurrentModel] = useState<string>("qwen2.5-coder:7b");
  const [healthStatus, setHealthStatus] = useState<Record<string, unknown> | null>(null);
  const [activity, setActivity] = useState<AgentActivityEvent[]>([]);
  const [servers, setServers] = useState<{ id: string; script: string; port: number; url: string }[]>([]);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let active = true;
    const init = async () => {
      try {
        const [healthResp, modelsResp, actResp, srvResp] = await Promise.all([
          fetch(`${apiUrl}/api/health`),
          fetch(`${apiUrl}/api/models`),
          fetch(`${apiUrl}/api/agent/activity?limit=30`),
          fetch(`${apiUrl}/api/agent/servers`),
        ]);
        const hData = healthResp.ok ? await healthResp.json() : null;
        const mData = modelsResp.ok ? await modelsResp.json() : null;
        const actData = actResp.ok ? await actResp.json() : null;
        const srvData = srvResp.ok ? await srvResp.json() : null;
        if (!active) return;
        if (hData) setHealthStatus(hData);
        if (mData) {
          setModels(mData.installed_models || []);
          if (mData.current_model) setCurrentModel(mData.current_model);
        }
        if (actData) setActivity(actData.events || []);
        if (srvData) setServers(srvData.servers || []);
      } catch {
        if (active) setErrorMessage("Could not connect to backend diagnostics");
      }
    };
    void init();
    return () => {
      active = false;
    };
  }, [apiUrl]);

  async function loadSettingsAndHealth() {
    try {
      const [healthResp, modelsResp, actResp, srvResp] = await Promise.all([
        fetch(`${apiUrl}/api/health`),
        fetch(`${apiUrl}/api/models`),
        fetch(`${apiUrl}/api/agent/activity?limit=30`),
        fetch(`${apiUrl}/api/agent/servers`),
      ]);
      const hData = healthResp.ok ? await healthResp.json() : null;
      const mData = modelsResp.ok ? await modelsResp.json() : null;
      const actData = actResp.ok ? await actResp.json() : null;
      const srvData = srvResp.ok ? await srvResp.json() : null;
      if (hData) setHealthStatus(hData);
      if (mData) {
        setModels(mData.installed_models || []);
        if (mData.current_model) setCurrentModel(mData.current_model);
      }
      if (actData) setActivity(actData.events || []);
      if (srvData) setServers(srvData.servers || []);
    } catch {
      setErrorMessage("Could not connect to backend diagnostics");
    }
  }

  async function handleSelectModel(modelName: string) {
    try {
      const resp = await fetch(`${apiUrl}/api/models/select`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: modelName }),
      });
      if (resp.ok) {
        setCurrentModel(modelName);
        setStatusMessage(`Selected local model: ${modelName}`);
        void loadSettingsAndHealth();
      }
    } catch {
      setErrorMessage("Failed to select model");
    }
  }

  async function handleStopServer(serverId: string) {
    try {
      const resp = await fetch(`${apiUrl}/api/agent/servers/${serverId}/stop`, { method: "POST" });
      if (resp.ok) {
        setStatusMessage(`Stopped local server ${serverId}`);
        void loadSettingsAndHealth();
      }
    } catch {
      setErrorMessage("Failed to stop server");
    }
  }

  return (
    <div className="view-container">
      <header className="view-header">
        <div>
          <span className="eyebrow">SETTINGS & SYSTEM DIAGNOSTICS</span>
          <h2>Runtime, Model & Audit Logs</h2>
          <p className="view-desc">
            Monitor local Ollama service, model tags, workspace servers, security audits, and UI appearance.
          </p>
        </div>
        <button className="primary-btn" onClick={() => void loadSettingsAndHealth()}>
          Refresh Diagnostics
        </button>
      </header>

      {statusMessage && <div className="notice-banner success">{statusMessage}</div>}
      {errorMessage && <div className="notice-banner error">{errorMessage}</div>}

      <div className="view-grid">
        {/* Left Column: Model & Runtime */}
        <div className="panel-card">
          <h3>Local Model & Runtime</h3>
          <p className="card-desc">Nexus AI defaults to local inference for complete privacy.</p>

          <div className="runtime-status-box">
            <div className="status-indicator-row">
              <span className={`status-dot ${healthStatus?.ollama_reachable ? "" : "status-warning"}`} />
              <strong>
                Ollama: {healthStatus?.ollama_reachable ? "Online (127.0.0.1:11434)" : "Unreachable"}
              </strong>
            </div>
            <p className="status-msg">{String(healthStatus?.message || "Checking status...")}</p>
          </div>

          <div className="input-group">
            <label>Selected Model Tag</label>
            <select
              value={currentModel}
              onChange={(e) => void handleSelectModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {!models.includes(currentModel) && (
                <option value={currentModel}>{currentModel} (active)</option>
              )}
            </select>
            <span className="input-help">Installed local models reported by Ollama.</span>
          </div>

          <hr className="divider" />

          <h3>Appearance</h3>
          <div className="theme-toggle-row">
            <div>
              <strong>Interface Theme</strong>
              <p className="card-desc">Current: {theme === "dark" ? "Dark Mode" : "Light Mode"}</p>
            </div>
            <button className="secondary-btn" onClick={onToggleTheme}>
              Switch to {theme === "dark" ? "Light Mode" : "Dark Mode"}
            </button>
          </div>

          <hr className="divider" />

          <h3>Active Local Servers ({servers.length})</h3>
          <p className="card-desc">Python servers started by coding agent within the workspace.</p>
          {servers.length === 0 ? (
            <p className="empty-results">No active local servers running.</p>
          ) : (
            <div className="servers-list">
              {servers.map((s) => (
                <div className="server-item" key={s.id}>
                  <div>
                    <strong>{s.script}</strong> on port {s.port}
                    <br />
                    <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
                  </div>
                  <button className="btn-sm btn-danger" onClick={() => void handleStopServer(s.id)}>
                    Stop
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right Column: Security & Audit Activity Log */}
        <div className="panel-card">
          <h3>Security Audit & Activity Log</h3>
          <p className="card-desc">
            Immutable log of all agent tool actions, approval tickets, and classified risks.
          </p>

          {activity.length === 0 ? (
            <div className="empty-state">
              <p>No recent activity recorded.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Risk</th>
                    <th>Action</th>
                    <th>Event</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {activity.map((ev, i) => (
                    <tr key={`${ev.activity_id}-${i}`}>
                      <td><code>{ev.created_at?.slice(11, 19) || "—"}</code></td>
                      <td>
                        <span className={`risk-tag risk-${ev.risk?.toLowerCase()}`}>
                          {ev.risk}
                        </span>
                      </td>
                      <td><code>{ev.action}</code></td>
                      <td>{ev.event}</td>
                      <td className="truncate-cell" title={ev.target}>{ev.target || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
