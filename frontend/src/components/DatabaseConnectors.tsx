import { useEffect, useState } from "react";
import type { DatabaseConnector, QueryResult, SchemaInspection } from "../types";

type Props = {
  apiUrl: string;
};

export default function DatabaseConnectors({ apiUrl }: Props) {
  const [connectors, setConnectors] = useState<DatabaseConnector[]>([]);
  const [selectedConnector, setSelectedConnector] = useState<string>("primary_sqlite");
  const [schema, setSchema] = useState<SchemaInspection | null>(null);
  const [queryInput, setQueryInput] = useState<string>("SELECT * FROM conversations LIMIT 10");
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; latency_ms?: number } | null>(null);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  // New connector form state
  const [showAddModal, setShowAddModal] = useState(false);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [newType, setNewType] = useState("sqlite");
  const [newConfigPath, setNewConfigPath] = useState("");

  useEffect(() => {
    let active = true;
    fetch(`${apiUrl}/api/connectors`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setConnectors(data.connectors || []);
      })
      .catch(() => {
        if (active) setErrorMessage("Failed to load connectors");
      });
    return () => {
      active = false;
    };
  }, [apiUrl]);

  useEffect(() => {
    if (!selectedConnector) return;
    let active = true;
    fetch(`${apiUrl}/api/connectors/${selectedConnector}/schema`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active) setSchema(data);
      })
      .catch(() => {
        if (active) setSchema(null);
      });
    return () => {
      active = false;
    };
  }, [apiUrl, selectedConnector]);

  async function loadConnectors() {
    setLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/api/connectors`);
      if (resp.ok) {
        const data = await resp.json();
        setConnectors(data.connectors || []);
      }
    } catch {
      setErrorMessage("Failed to load connectors");
    } finally {
      setLoading(false);
    }
  }

  async function inspectSelectedSchema(connectorId: string) {
    try {
      const resp = await fetch(`${apiUrl}/api/connectors/${connectorId}/schema`);
      if (resp.ok) {
        const data = await resp.json();
        setSchema(data);
      }
    } catch {
      setSchema(null);
    }
  }

  async function handleTestConnection(connectorId: string) {
    setTesting(true);
    setTestResult(null);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/connectors/${connectorId}/test`);
      const data = await resp.json();
      setTestResult(data);
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : "Connection test failed",
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleExecuteQuery() {
    if (!queryInput.trim() || !selectedConnector) return;
    setLoading(true);
    setQueryResult(null);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/connectors/${selectedConnector}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: queryInput.trim(), max_rows: 50 }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || "Query execution failed");
      }
      setQueryResult(data);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Query execution failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleCreateConnector() {
    if (!newId.trim() || !newName.trim()) return;
    try {
      const config = newType === "sqlite" ? { db_path: newConfigPath.trim() } : { path: newConfigPath.trim() };
      const resp = await fetch(`${apiUrl}/api/connectors`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: newId.trim(),
          name: newName.trim(),
          connector_type: newType,
          config,
          is_read_only: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to register connector");
      setStatusMessage(`Successfully registered connector "${newName}"`);
      setShowAddModal(false);
      setNewId("");
      setNewName("");
      setNewConfigPath("");
      void loadConnectors();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Connector registration error");
    }
  }

  async function handleDeleteConnector(id: string) {
    if (!window.confirm(`Delete connector "${id}"?`)) return;
    try {
      const resp = await fetch(`${apiUrl}/api/connectors/${id}`, { method: "DELETE" });
      if (resp.ok) {
        setStatusMessage(`Deleted connector "${id}"`);
        if (selectedConnector === id) setSelectedConnector("primary_sqlite");
        void loadConnectors();
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to delete connector");
    }
  }

  return (
    <div className="view-container">
      <header className="view-header">
        <div>
          <span className="eyebrow">DATA CONNECTORS</span>
          <h2>Database & Structured Data Framework</h2>
          <p className="view-desc">
            Isolated read-only connectors for SQLite, CSV datasets, and external database adapters with sensitive column redaction.
          </p>
        </div>
        <div className="header-actions">
          <button className="secondary-btn" onClick={() => void loadConnectors()}>Refresh</button>
          <button className="primary-btn" onClick={() => setShowAddModal(true)}>+ Add Connector</button>
        </div>
      </header>

      {statusMessage && <div className="notice-banner success">{statusMessage}</div>}
      {errorMessage && <div className="notice-banner error">{errorMessage}</div>}

      <div className="view-grid">
        {/* Left Column: Registered Connectors */}
        <div className="panel-card">
          <h3>Registered Connectors</h3>
          <p className="card-desc">Read-only enforcement is active across all external database interactions.</p>

          <div className="connector-list">
            {connectors.map((conn) => (
              <div
                key={conn.id}
                className={`connector-card ${selectedConnector === conn.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedConnector(conn.id);
                  setTestResult(null);
                  setQueryResult(null);
                  void inspectSelectedSchema(conn.id);
                  if (conn.connector_type === "sqlite") {
                    setQueryInput("SELECT * FROM conversations LIMIT 10");
                  } else {
                    setQueryInput("");
                  }
                }}
              >
                <div className="connector-card-header">
                  <strong>{conn.name}</strong>
                  <span className="badge-type">{conn.connector_type}</span>
                </div>
                <div className="connector-card-meta">
                  <span>ID: <code>{conn.id}</code></span>
                  <span className="badge-ro">{conn.is_read_only ? "Strict Read-Only" : "Read-Write"}</span>
                </div>
                <div className="connector-card-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="btn-xs"
                    onClick={() => void handleTestConnection(conn.id)}
                    disabled={testing}
                  >
                    Test Connection
                  </button>
                  {conn.id !== "primary_sqlite" && conn.id !== "web_search" && (
                    <button
                      className="btn-xs btn-danger"
                      onClick={() => void handleDeleteConnector(conn.id)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          {testResult && (
            <div className={`test-result-box ${testResult.success ? "success" : "failed"}`}>
              <strong>{testResult.success ? "Connection Verified" : "Connection Failed"}</strong>
              <p>{testResult.message}</p>
              {testResult.latency_ms !== undefined && <span>Latency: {testResult.latency_ms} ms</span>}
            </div>
          )}

          {/* Schema Introspection */}
          {schema && (
            <div className="schema-section">
              <hr className="divider" />
              <h3>Schema Introspection ({schema.table_count} tables)</h3>
              <div className="tables-accordion">
                {schema.tables?.map((table) => (
                  <details className="table-schema-item" key={table.name}>
                    <summary>
                      <strong>{table.name}</strong>
                      <span className="row-badge">{table.row_count} rows</span>
                    </summary>
                    <ul className="column-list">
                      {table.columns?.map((col) => (
                        <li key={col.name}>
                          <code>{col.name}</code> <span className="col-type">({col.type})</span>
                          {col.pk && <span className="pk-badge">PK</span>}
                        </li>
                      ))}
                    </ul>
                  </details>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Query Console */}
        <div className="panel-card">
          <h3>Read-Only Query Console</h3>
          <p className="card-desc">
            Executes safe SELECT queries. Mutation commands (INSERT, UPDATE, DELETE, DROP) are strictly rejected.
          </p>

          <div className="query-box">
            <textarea
              rows={4}
              value={queryInput}
              onChange={(e) => setQueryInput(e.target.value)}
              placeholder="SELECT * FROM table_name WHERE ..."
            />
            <div className="query-actions">
              <span className="target-indicator">Target: <code>{selectedConnector}</code></span>
              <button
                className="primary-btn"
                onClick={() => void handleExecuteQuery()}
                disabled={loading || !queryInput.trim()}
              >
                {loading ? "Running Query..." : "Execute Query"}
              </button>
            </div>
          </div>

          {/* Query Results */}
          {queryResult && (
            <div className="query-results-section">
              <div className="results-header">
                <h4>Query Results ({queryResult.row_count} rows)</h4>
                {queryResult.truncated && <span className="truncated-badge">Truncated at max rows</span>}
              </div>

              {queryResult.rows.length === 0 ? (
                <p className="empty-results">Query returned 0 rows.</p>
              ) : (
                <div className="table-responsive">
                  <table className="data-table">
                    <thead>
                      <tr>
                        {queryResult.columns.map((c) => (
                          <th key={c}>{c}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {queryResult.rows.map((row, rIdx) => (
                        <tr key={rIdx}>
                          {row.map((val, cIdx) => (
                            <td key={cIdx}>
                              {val === null ? <em>NULL</em> : String(val)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Add Connector Modal */}
      {showAddModal && (
        <div className="modal-backdrop">
          <div className="modal-card">
            <h3>Add Database Connector</h3>
            <div className="input-group">
              <label>Connector Type</label>
              <select value={newType} onChange={(e) => setNewType(e.target.value)}>
                <option value="sqlite">SQLite Database (.db/.sqlite)</option>
                <option value="csv">CSV Dataset (File or Directory)</option>
                <option value="postgresql">PostgreSQL (Adapter)</option>
                <option value="mysql">MySQL (Adapter)</option>
              </select>
            </div>
            <div className="input-group">
              <label>Connector Identifier</label>
              <input
                type="text"
                value={newId}
                onChange={(e) => setNewId(e.target.value)}
                placeholder="e.g. analytics_db"
              />
            </div>
            <div className="input-group">
              <label>Display Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="e.g. Sales Analytics Database"
              />
            </div>
            <div className="input-group">
              <label>Path or Connection String</label>
              <input
                type="text"
                value={newConfigPath}
                onChange={(e) => setNewConfigPath(e.target.value)}
                placeholder="C:\path\to\database.db"
              />
            </div>
            <div className="modal-actions">
              <button className="secondary-btn" onClick={() => setShowAddModal(false)}>Cancel</button>
              <button className="primary-btn" onClick={() => void handleCreateConnector()}>Save Connector</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
