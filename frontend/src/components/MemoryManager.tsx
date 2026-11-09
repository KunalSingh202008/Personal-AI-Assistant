import { useEffect, useState } from "react";

type Props = {
  apiUrl: string;
};

export default function MemoryManager({ apiUrl }: Props) {
  const [preferences, setPreferences] = useState<Record<string, string>>({});
  const [newKey, setNewKey] = useState("");
  const [newValue, setNewValue] = useState("");
  const [newCategory, setNewCategory] = useState("general");
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${apiUrl}/api/memory/preferences`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setPreferences(data.preferences || {});
      })
      .catch(() => {
        if (active) setErrorMessage("Failed to load user preferences");
      });
    return () => {
      active = false;
    };
  }, [apiUrl]);

  async function loadPreferences() {
    setLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/api/memory/preferences`);
      if (resp.ok) {
        const data = await resp.json();
        setPreferences(data.preferences || {});
      }
    } catch {
      setErrorMessage("Failed to load user preferences");
    } finally {
      setLoading(false);
    }
  }

  async function handleSavePreference() {
    if (!newKey.trim() || !newValue.trim()) return;
    try {
      const resp = await fetch(`${apiUrl}/api/memory/preferences`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          key: newKey.trim(),
          value: newValue.trim(),
          category: newCategory,
        }),
      });
      if (resp.ok) {
        setStatusMessage(`Saved preference "${newKey}"`);
        setNewKey("");
        setNewValue("");
        void loadPreferences();
      }
    } catch {
      setErrorMessage("Failed to save preference");
    }
  }

  async function handleDeletePreference(key: string) {
    try {
      const resp = await fetch(`${apiUrl}/api/memory/preferences/${encodeURIComponent(key)}`, {
        method: "DELETE",
      });
      if (resp.ok) {
        setStatusMessage(`Deleted preference "${key}"`);
        void loadPreferences();
      }
    } catch {
      setErrorMessage("Failed to delete preference");
    }
  }

  async function handleExportSnapshot() {
    try {
      const resp = await fetch(`${apiUrl}/api/memory/export`);
      if (resp.ok) {
        const data = await resp.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `nexus_memory_snapshot_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
        setStatusMessage("Downloaded memory snapshot JSON.");
      }
    } catch {
      setErrorMessage("Failed to export memory snapshot");
    }
  }

  async function handleClearMemory() {
    if (!window.confirm("Are you sure you want to clear all persistent preferences and workspace contexts?")) {
      return;
    }
    try {
      const resp = await fetch(`${apiUrl}/api/memory/clear`, { method: "POST" });
      if (resp.ok) {
        setStatusMessage("Cleared memory store successfully.");
        void loadPreferences();
      }
    } catch {
      setErrorMessage("Failed to clear memory");
    }
  }

  return (
    <div className="view-container">
      <header className="view-header">
        <div>
          <span className="eyebrow">PERSONAL MEMORY & CONTEXT</span>
          <h2>Isolated Memory Architecture</h2>
          <p className="view-desc">
            Nexus AI maintains strict firewalls between conversation history, persistent user preferences,
            workspace project context, indexed knowledge, and ephemeral agent task states.
          </p>
        </div>
        <div className="header-actions">
          <button className="secondary-btn" onClick={() => void loadPreferences()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          <button className="secondary-btn" onClick={() => void handleExportSnapshot()}>Export Snapshot</button>
          <button className="secondary-btn btn-danger" onClick={() => void handleClearMemory()}>Clear Memory</button>
        </div>
      </header>

      {statusMessage && <div className="notice-banner success">{statusMessage}</div>}
      {errorMessage && <div className="notice-banner error">{errorMessage}</div>}

      <div className="memory-layers-grid">
        <div className="memory-layer-card">
          <div className="layer-badge">Layer 1</div>
          <h4>Conversation History</h4>
          <p>Multi-turn chats, idempotent client message IDs, persistent SQLite database.</p>
          <span className="layer-status">Managed via Chat Panel</span>
        </div>

        <div className="memory-layer-card active">
          <div className="layer-badge">Layer 2</div>
          <h4>Persistent Preferences</h4>
          <p>User profile facts, communication style, formatting rules, coding standards.</p>
          <span className="layer-status">{Object.keys(preferences).length} active preferences</span>
        </div>

        <div className="memory-layer-card">
          <div className="layer-badge">Layer 3</div>
          <h4>Workspace Context</h4>
          <p>Per-project architecture constraints, technology choices (up to 8,000 chars).</p>
          <span className="layer-status">Scoped per project path</span>
        </div>

        <div className="memory-layer-card">
          <div className="layer-badge">Layer 4</div>
          <h4>Retrieved Knowledge</h4>
          <p>Evidence retrieved dynamically from local documents & databases on demand.</p>
          <span className="layer-status">FTS5 + Semantic Vectors</span>
        </div>

        <div className="memory-layer-card">
          <div className="layer-badge">Layer 5</div>
          <h4>Ephemeral Task State</h4>
          <p>Active coding plans, execution timelines, verification passes, and tool diffs.</p>
          <span className="layer-status">Scoped to active task ID</span>
        </div>
      </div>

      <div className="view-grid">
        {/* Left Column: Manage Persistent Preferences */}
        <div className="panel-card">
          <h3>Add / Update Persistent Preference</h3>
          <p className="card-desc">
            Preferences are injected cleanly into model prompts without polluting document indices or workspace state.
          </p>

          <div className="input-group">
            <label>Category</label>
            <select value={newCategory} onChange={(e) => setNewCategory(e.target.value)}>
              <option value="general">General / Persona</option>
              <option value="coding">Coding Style & Conventions</option>
              <option value="research">Research & Reasoning Format</option>
              <option value="privacy">Privacy & Confidentiality</option>
            </select>
          </div>

          <div className="input-group">
            <label>Preference Key</label>
            <input
              type="text"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="e.g. tone, language, default_framework"
            />
          </div>

          <div className="input-group">
            <label>Preference Value / Directive</label>
            <textarea
              rows={3}
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder="e.g. Always include concise summaries and TypeScript types."
            />
          </div>

          <button
            className="primary-btn"
            onClick={() => void handleSavePreference()}
            disabled={!newKey.trim() || !newValue.trim()}
          >
            Save Preference
          </button>
        </div>

        {/* Right Column: Active Preferences Table */}
        <div className="panel-card">
          <h3>Configured User Preferences ({Object.keys(preferences).length})</h3>
          <p className="card-desc">Saved locally in SQLite. Edit or remove anytime.</p>

          {Object.keys(preferences).length === 0 ? (
            <div className="empty-state">
              <p>No persistent preferences defined. Add your first preference to customize the assistant.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Directive / Value</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(preferences).map(([k, v]) => (
                    <tr key={k}>
                      <td><code>{k}</code></td>
                      <td>{v}</td>
                      <td>
                        <button
                          className="btn-sm btn-danger"
                          onClick={() => void handleDeletePreference(k)}
                        >
                          Remove
                        </button>
                      </td>
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
