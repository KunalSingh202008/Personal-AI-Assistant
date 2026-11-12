import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import type { KnowledgeBase, KnowledgeDoc, SearchResult } from "../types";

type Props = {
  apiUrl: string;
};

export default function KnowledgeManager({ apiUrl }: Props) {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string>("default");
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<KnowledgeDoc | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  // New Knowledge Base creation form
  const [showCreateKb, setShowCreateKb] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [newKbDesc, setNewKbDesc] = useState("");
  const [newKbProject, setNewKbProject] = useState("default");
  const [newKbModel, setNewKbModel] = useState("local-fast");

  // Ingestion inputs
  const [filePathInput, setFilePathInput] = useState("");
  const [dirPathInput, setDirPathInput] = useState("");
  const [dirRecursive, setDirRecursive] = useState(true);

  // Search tester
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  // Initial load
  useEffect(() => {
    let active = true;
    fetch(`${apiUrl}/api/knowledge/bases`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setKnowledgeBases(data.knowledge_bases || []);
      })
      .catch((err) => {
        if (active) setErrorMessage(err instanceof Error ? err.message : "Failed to load knowledge bases");
      });
    return () => {
      active = false;
    };
  }, [apiUrl]);

  // When selected KB changes, fetch its documents
  useEffect(() => {
    if (!selectedKbId) return;
    let active = true;
    fetch(`${apiUrl}/api/knowledge/bases/${encodeURIComponent(selectedKbId)}/documents`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (active && data) setDocuments(data.documents || []);
      })
      .catch((err) => {
        if (active) setErrorMessage(err instanceof Error ? err.message : "Failed to load documents");
      });
    return () => {
      active = false;
    };
  }, [apiUrl, selectedKbId]);

  const loadKnowledgeBases = async () => {
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/bases`);
      if (resp.ok) {
        const data = await resp.json();
        const kbs: KnowledgeBase[] = data.knowledge_bases || [];
        setKnowledgeBases(kbs);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load knowledge bases");
    }
  };

  const loadDocuments = async (kbId: string = selectedKbId) => {
    setLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/bases/${encodeURIComponent(kbId)}/documents`);
      if (resp.ok) {
        const data = await resp.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  };

  const handleSelectKb = (kbId: string) => {
    setSelectedKbId(kbId);
    setSelectedDoc(null);
    setSearchResults([]);
  };

  async function handleCreateKb() {
    if (!newKbName.trim()) return;
    setStatusMessage("Creating knowledge base...");
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/bases`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newKbName.trim(),
          description: newKbDesc.trim(),
          owner_project: newKbProject.trim() || "default",
          embedding_model: newKbModel,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Failed to create knowledge base");
      setStatusMessage(`Knowledge base "${data.knowledge_base.name}" created successfully.`);
      setNewKbName("");
      setNewKbDesc("");
      setShowCreateKb(false);
      await loadKnowledgeBases();
      setSelectedKbId(data.knowledge_base.id);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to create knowledge base");
    }
  }

  async function handleDeleteKb(kbId: string, kbName: string) {
    if (kbId === "default") {
      if (!window.confirm("Default Knowledge Base cannot be removed, but its documents will be cleared. Proceed?")) return;
    } else {
      if (!window.confirm(`Permanently delete knowledge base "${kbName}" and all its datasets? This cannot be undone.`)) return;
    }

    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/bases/${encodeURIComponent(kbId)}`, {
        method: "DELETE",
      });
      if (resp.ok) {
        setStatusMessage(`Deleted knowledge base "${kbName}".`);
        await loadKnowledgeBases();
        setSelectedKbId("default");
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to delete knowledge base");
    }
  }

  async function handleReindexKb() {
    setStatusMessage(`Re-indexing knowledge base "${selectedKbId}"...`);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/bases/${encodeURIComponent(selectedKbId)}/reindex`, {
        method: "POST",
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Reindex failed");
      setStatusMessage(`Reindex complete: ${data.reindexed} reindexed, ${data.failed} failed.`);
      await loadKnowledgeBases();
      void loadDocuments(selectedKbId);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Reindex failed");
    }
  }

  async function handleIndexFile() {
    if (!filePathInput.trim()) return;
    setStatusMessage(`Indexing file into "${selectedKbId}"...`);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/index-file`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePathInput.trim(), kb_id: selectedKbId }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Indexing failed");
      setStatusMessage(`Indexed "${data.title}" (${data.chunk_count} chunks, status: ${data.status})`);
      setFilePathInput("");
      await loadKnowledgeBases();
      void loadDocuments(selectedKbId);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to index file");
    }
  }

  async function handleIndexDirectory() {
    if (!dirPathInput.trim()) return;
    setStatusMessage(`Scanning and indexing directory into "${selectedKbId}"...`);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/index-directory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: dirPathInput.trim(),
          kb_id: selectedKbId,
          recursive: dirRecursive,
        }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Directory indexing failed");
      setStatusMessage(
        `Directory complete: ${data.indexed} indexed, ${data.skipped} skipped, ${data.failed} failed`,
      );
      setDirPathInput("");
      await loadKnowledgeBases();
      void loadDocuments(selectedKbId);
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to index directory");
    }
  }

  async function handleFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setStatusMessage(`Uploading and indexing "${file.name}" into "${selectedKbId}"...`);
    setErrorMessage("");

    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const content = reader.result as string;
        const resp = await fetch(`${apiUrl}/api/knowledge/upload`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, content, kb_id: selectedKbId }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Upload indexing failed");
        setStatusMessage(`Successfully indexed "${file.name}" (${data.chunk_count} chunks)`);
        await loadKnowledgeBases();
        void loadDocuments(selectedKbId);
      } catch (err) {
        setErrorMessage(err instanceof Error ? err.message : "Upload failed");
      }
    };
    reader.onerror = () => setErrorMessage("Could not read uploaded file");
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  async function handleDeleteDocument(docId: number, title: string) {
    if (!window.confirm(`Delete "${title}" and all its index chunks?`)) return;
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/documents/${docId}`, {
        method: "DELETE",
      });
      if (resp.ok) {
        setStatusMessage(`Deleted "${title}" from index.`);
        if (selectedDoc?.id === docId) setSelectedDoc(null);
        await loadKnowledgeBases();
        void loadDocuments(selectedKbId);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Deletion failed");
    }
  }

  async function handleInspectDoc(docId: number) {
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/documents/${docId}`);
      if (resp.ok) {
        const data = await resp.json();
        setSelectedDoc(data.document);
      }
    } catch {
      setErrorMessage("Could not inspect document details");
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: searchQuery.trim(),
          kb_id: selectedKbId,
          top_k: 5,
          hybrid: true,
        }),
      });
      const data = await resp.json();
      if (resp.ok) {
        setSearchResults(data.results || []);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Search failed");
    } finally {
      setSearching(false);
    }
  }

  const currentKb = knowledgeBases.find((k) => k.id === selectedKbId);

  return (
    <div className="view-container">
      <header className="view-header">
        <div>
          <span className="eyebrow">MULTI-DATASET KNOWLEDGE ENGINE</span>
          <h2>Knowledge Bases & RAG Studio</h2>
          <p className="view-desc">
            Isolated knowledge base workspaces, multi-dataset ingestion (PDF, DOCX, XLSX, CSV, JSON, MD),
            and FTS5 + semantic vector hybrid retrieval with genuine source citations.
          </p>
        </div>
        <div className="header-actions" style={{ display: "flex", gap: "0.5rem" }}>
          <button className="secondary-btn" onClick={() => setShowCreateKb(true)}>
            + New Knowledge Base
          </button>
          <button className="primary-btn" onClick={() => void loadDocuments()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh Catalog"}
          </button>
        </div>
      </header>

      {statusMessage && <div className="notice-banner success">{statusMessage}</div>}
      {errorMessage && <div className="notice-banner error">{errorMessage}</div>}

      {/* Knowledge Base Switcher Bar */}
      <div className="kb-switcher-bar" style={{
        background: "var(--bg-secondary, #1a1a24)",
        padding: "0.75rem 1rem",
        borderRadius: "8px",
        marginBottom: "1rem",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "1rem",
        flexWrap: "wrap",
        border: "1px solid var(--border-color, #2d2d3d)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <label style={{ fontWeight: 600, fontSize: "0.9rem" }}>Active Knowledge Base:</label>
          <select
            value={selectedKbId}
            onChange={(e) => handleSelectKb(e.target.value)}
            style={{
              padding: "0.4rem 0.8rem",
              borderRadius: "6px",
              background: "var(--bg-card, #232332)",
              color: "inherit",
              border: "1px solid var(--border-color, #3d3d52)",
              fontWeight: 500,
            }}
          >
            {knowledgeBases.map((kb) => (
              <option key={kb.id} value={kb.id}>
                {kb.name} ({kb.document_count || 0} docs, {kb.total_chunks || 0} chunks)
              </option>
            ))}
          </select>
        </div>

        {currentKb && (
          <div style={{ display: "flex", alignItems: "center", gap: "1rem", fontSize: "0.85rem" }}>
            <span><strong>Model:</strong> {currentKb.embedding_model} ({currentKb.embedding_dim}d)</span>
            <span><strong>Project:</strong> {currentKb.owner_project}</span>
            <div style={{ display: "flex", gap: "0.4rem" }}>
              <button
                className="btn-sm"
                onClick={() => void handleReindexKb()}
                title="Re-run embeddings and index for this KB"
              >
                Reindex KB
              </button>
              {selectedKbId !== "default" && (
                <button
                  className="btn-sm btn-danger"
                  onClick={() => void handleDeleteKb(currentKb.id, currentKb.name)}
                  title="Delete this knowledge base"
                >
                  Delete KB
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Modal: Create Knowledge Base */}
      {showCreateKb && (
        <div className="modal-backdrop" style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
          background: "rgba(0,0,0,0.65)", display: "flex", alignItems: "center",
          justifyContent: "center", zIndex: 1000,
        }}>
          <div className="modal-card" style={{
            background: "var(--bg-primary, #15151e)", padding: "1.5rem",
            borderRadius: "10px", width: "450px", maxWidth: "90%",
            border: "1px solid var(--border-color, #33334d)",
          }}>
            <h3>Create Isolated Knowledge Base</h3>
            <p className="card-desc">Datasets and vectors inside this knowledge base will be strictly isolated.</p>

            <div className="input-group" style={{ marginBottom: "0.75rem" }}>
              <label>Name</label>
              <input
                type="text"
                value={newKbName}
                onChange={(e) => setNewKbName(e.target.value)}
                placeholder="e.g. Legal Contracts, Finance 2026, Research Docs"
              />
            </div>

            <div className="input-group" style={{ marginBottom: "0.75rem" }}>
              <label>Description</label>
              <input
                type="text"
                value={newKbDesc}
                onChange={(e) => setNewKbDesc(e.target.value)}
                placeholder="Brief purpose of this knowledge base"
              />
            </div>

            <div className="input-group" style={{ marginBottom: "0.75rem" }}>
              <label>Owner Project</label>
              <input
                type="text"
                value={newKbProject}
                onChange={(e) => setNewKbProject(e.target.value)}
                placeholder="default"
              />
            </div>

            <div className="input-group" style={{ marginBottom: "1.25rem" }}>
              <label>Embedding Provider</label>
              <select
                value={newKbModel}
                onChange={(e) => setNewKbModel(e.target.value)}
                style={{ width: "100%", padding: "0.5rem", borderRadius: "6px" }}
              >
                <option value="local-fast">Fast Local Subword (128d - Pure Python, Instant)</option>
                <option value="ollama">Ollama nomic-embed-text (Local Model)</option>
              </select>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
              <button className="secondary-btn" onClick={() => setShowCreateKb(false)}>
                Cancel
              </button>
              <button
                className="primary-btn"
                onClick={() => void handleCreateKb()}
                disabled={!newKbName.trim()}
              >
                Create
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="view-grid">
        {/* Left Column: Ingestion Tools */}
        <div className="panel-card">
          <h3>Ingest Datasets into "{currentKb?.name || selectedKbId}"</h3>
          <p className="card-desc">
            Supported: PDF (multi-page citations), DOCX (tables & sections), XLSX (sheet citations), CSV, JSON, JSONL, TXT, MD.
          </p>

          <div className="input-group">
            <label>Upload document or dataset</label>
            <input type="file" onChange={(e) => void handleFileUpload(e)} />
          </div>

          <div className="input-group">
            <label htmlFor="file-path-input">Index single file by local path</label>
            <div className="input-row">
              <input
                id="file-path-input"
                type="text"
                value={filePathInput}
                onChange={(e) => setFilePathInput(e.target.value)}
                placeholder="C:\path\to\document.pdf"
              />
              <button onClick={() => void handleIndexFile()} disabled={!filePathInput.trim()}>
                Index File
              </button>
            </div>
          </div>

          <div className="input-group">
            <label htmlFor="dir-path-input">Index directory into this KB</label>
            <div className="input-row">
              <input
                id="dir-path-input"
                type="text"
                value={dirPathInput}
                onChange={(e) => setDirPathInput(e.target.value)}
                placeholder="C:\path\to\datasets_folder"
              />
              <button onClick={() => void handleIndexDirectory()} disabled={!dirPathInput.trim()}>
                Index Dir
              </button>
            </div>
            <label className="checkbox-label" style={{ marginTop: "0.4rem" }}>
              <input
                type="checkbox"
                checked={dirRecursive}
                onChange={(e) => setDirRecursive(e.target.checked)}
              />
              Recursive scan (subdirectories)
            </label>
          </div>

          <hr className="divider" />

          <h3>Hybrid Retrieval Tester</h3>
          <p className="card-desc">
            Test isolated BM25 lexical ranking + vector cosine similarity strictly within "{currentKb?.name || selectedKbId}".
          </p>
          <div className="input-row">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSearch();
              }}
              placeholder="Query this knowledge base..."
            />
            <button onClick={() => void handleSearch()} disabled={searching || !searchQuery.trim()}>
              {searching ? "Searching..." : "Search"}
            </button>
          </div>

          {searchResults.length > 0 && (
            <div className="search-results-list" style={{ marginTop: "1rem" }}>
              <h4>Retrieved Citations ({searchResults.length})</h4>
              {searchResults.map((res) => (
                <div className="search-result-item" key={res.citation_id} style={{
                  padding: "0.75rem",
                  background: "var(--bg-secondary, #1a1a24)",
                  borderRadius: "6px",
                  marginBottom: "0.5rem",
                  border: "1px solid var(--border-color, #2d2d3d)",
                }}>
                  <div className="result-header" style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.3rem" }}>
                    <span className="citation-badge" style={{
                      background: "var(--accent-color, #6366f1)",
                      color: "#fff",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      fontSize: "0.75rem",
                      fontWeight: 700,
                    }}>
                      {res.citation_id}
                    </span>
                    <strong>{res.title}</strong>
                    {res.page_number && (
                      <span className="page-badge" style={{
                        background: "#3b82f6", color: "#fff", padding: "1px 6px", borderRadius: "4px", fontSize: "0.75rem"
                      }}>
                        Page {res.page_number}
                      </span>
                    )}
                    {res.sheet_name && (
                      <span className="sheet-badge" style={{
                        background: "#10b981", color: "#fff", padding: "1px 6px", borderRadius: "4px", fontSize: "0.75rem"
                      }}>
                        Sheet: {res.sheet_name}
                      </span>
                    )}
                    <span className="result-score" style={{ marginLeft: "auto", fontSize: "0.8rem", color: "#9ca3af" }}>
                      Score: {res.score}
                    </span>
                  </div>
                  {res.start_line && !res.page_number && (
                    <div className="result-lines" style={{ fontSize: "0.8rem", color: "#9ca3af", marginBottom: "0.25rem" }}>
                      Lines {res.start_line}–{res.end_line}
                    </div>
                  )}
                  <p className="result-snippet" style={{ fontSize: "0.85rem", margin: 0, color: "#d1d5db" }}>
                    {res.snippet}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right Column: Indexed Documents Catalog */}
        <div className="panel-card">
          <h3>
            Datasets in "{currentKb?.name || selectedKbId}" ({documents.length})
          </h3>
          <p className="card-desc">
            Isolated documents and chunk embeddings stored in SQLite index for this knowledge base.
          </p>

          {documents.length === 0 ? (
            <div className="empty-state">
              <p>No documents indexed in this knowledge base yet. Ingest a file or folder on the left to begin.</p>
            </div>
          ) : (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Type</th>
                    <th>Chunks</th>
                    <th>Size</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {documents.map((doc) => (
                    <tr key={doc.id} className={selectedDoc?.id === doc.id ? "row-selected" : ""}>
                      <td title={doc.file_path}>
                        <strong>{doc.title}</strong>
                      </td>
                      <td><code>{doc.mime_type}</code></td>
                      <td>{doc.chunk_count}</td>
                      <td>{Math.round(doc.size_bytes / 1024)} KB</td>
                      <td>
                        <span className={`status-tag ${doc.status === "indexed" ? "tag-success" : "tag-danger"}`}>
                          {doc.status}
                        </span>
                      </td>
                      <td>
                        <div className="table-actions">
                          <button
                            className="btn-sm"
                            onClick={() => void handleInspectDoc(doc.id)}
                            title="Inspect chunks"
                          >
                            Inspect
                          </button>
                          <button
                            className="btn-sm btn-danger"
                            onClick={() => void handleDeleteDocument(doc.id, doc.title)}
                            title="Delete document"
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Chunk Inspector Drawer / Modal */}
          {selectedDoc && (
            <div className="doc-inspector" style={{ marginTop: "1.5rem" }}>
              <div className="inspector-header" style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "0.75rem" }}>
                <div>
                  <h4>Document: {selectedDoc.title}</h4>
                  <p className="inspector-path" style={{ fontSize: "0.8rem", color: "#9ca3af" }}>{selectedDoc.file_path}</p>
                </div>
                <button className="btn-sm" onClick={() => setSelectedDoc(null)}>Close</button>
              </div>

              <h5>Indexed Chunks ({selectedDoc.chunks?.length || 0})</h5>
              <div className="chunks-list" style={{ maxHeight: "350px", overflowY: "auto", display: "flex", flexDirection: "column", gap: "0.5rem" }}>
                {selectedDoc.chunks?.map((chunk) => (
                  <div className="chunk-card" key={chunk.id} style={{
                    padding: "0.6rem", background: "var(--bg-secondary, #1a1a24)", borderRadius: "6px", border: "1px solid var(--border-color, #2d2d3d)"
                  }}>
                    <div className="chunk-meta" style={{ display: "flex", gap: "0.75rem", fontSize: "0.8rem", color: "#9ca3af", marginBottom: "0.3rem" }}>
                      <span>Chunk #{chunk.chunk_index + 1}</span>
                      <span>{chunk.token_count} tokens</span>
                      {chunk.page_number && (
                        <span style={{ color: "#60a5fa", fontWeight: 600 }}>Page {chunk.page_number}</span>
                      )}
                      {chunk.sheet_name && (
                        <span style={{ color: "#34d399", fontWeight: 600 }}>Sheet: {chunk.sheet_name}</span>
                      )}
                      {chunk.start_line && !chunk.page_number && (
                        <span>Lines {chunk.start_line}–{chunk.end_line}</span>
                      )}
                    </div>
                    <pre className="chunk-content" style={{ margin: 0, fontSize: "0.85rem", whiteSpace: "pre-wrap", maxHeight: "150px", overflowY: "auto" }}>
                      <code>{chunk.content}</code>
                    </pre>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
