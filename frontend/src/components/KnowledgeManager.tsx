import { useEffect, useState } from "react";
import type { ChangeEvent } from "react";
import type { KnowledgeDoc, SearchResult } from "../types";

type Props = {
  apiUrl: string;
};

export default function KnowledgeManager({ apiUrl }: Props) {
  const [documents, setDocuments] = useState<KnowledgeDoc[]>([]);
  const [selectedDoc, setSelectedDoc] = useState<KnowledgeDoc | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  // Ingestion inputs
  const [filePathInput, setFilePathInput] = useState("");
  const [dirPathInput, setDirPathInput] = useState("");
  const [dirRecursive, setDirRecursive] = useState(true);

  // Search tester
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    let active = true;
    fetch(`${apiUrl}/api/knowledge/documents`)
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
  }, [apiUrl]);

  async function loadDocuments() {
    setLoading(true);
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/documents`);
      if (resp.ok) {
        const data = await resp.json();
        setDocuments(data.documents || []);
      }
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to load documents");
    } finally {
      setLoading(false);
    }
  }

  async function handleIndexFile() {
    if (!filePathInput.trim()) return;
    setStatusMessage("Indexing file...");
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/index-file`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: filePathInput.trim() }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Indexing failed");
      setStatusMessage(`Indexed "${data.title}" (${data.chunk_count} chunks, status: ${data.status})`);
      setFilePathInput("");
      void loadDocuments();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to index file");
    }
  }

  async function handleIndexDirectory() {
    if (!dirPathInput.trim()) return;
    setStatusMessage("Scanning and indexing directory...");
    setErrorMessage("");
    try {
      const resp = await fetch(`${apiUrl}/api/knowledge/index-directory`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: dirPathInput.trim(), recursive: dirRecursive }),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Directory indexing failed");
      setStatusMessage(
        `Directory complete: ${data.indexed} indexed, ${data.skipped} skipped, ${data.failed} failed`,
      );
      setDirPathInput("");
      void loadDocuments();
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to index directory");
    }
  }

  async function handleFileUpload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setStatusMessage(`Uploading and indexing "${file.name}"...`);
    setErrorMessage("");

    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const content = reader.result as string;
        const resp = await fetch(`${apiUrl}/api/knowledge/upload`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename: file.name, content }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Upload indexing failed");
        setStatusMessage(`Successfully indexed "${file.name}" (${data.chunk_count} chunks)`);
        void loadDocuments();
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
        void loadDocuments();
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
        body: JSON.stringify({ query: searchQuery.trim(), top_k: 5, hybrid: true }),
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

  return (
    <div className="view-container">
      <header className="view-header">
        <div>
          <span className="eyebrow">KNOWLEDGE ENGINE</span>
          <h2>Document Intelligence & Vector Store</h2>
          <p className="view-desc">
            Local multi-source knowledge ingestion, recursive chunking, and FTS5 + semantic vector hybrid retrieval.
          </p>
        </div>
        <button className="primary-btn" onClick={() => void loadDocuments()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh Catalog"}
        </button>
      </header>

      {statusMessage && <div className="notice-banner success">{statusMessage}</div>}
      {errorMessage && <div className="notice-banner error">{errorMessage}</div>}

      <div className="view-grid">
        {/* Left Column: Ingestion Tools */}
        <div className="panel-card">
          <h3>Ingest Knowledge Sources</h3>
          <p className="card-desc">Supported: TXT, Markdown, Python, TypeScript, PDF, CSV, JSON, YAML.</p>

          <div className="input-group">
            <label>Upload local file</label>
            <input type="file" onChange={(e) => void handleFileUpload(e)} />
          </div>

          <div className="input-group">
            <label htmlFor="file-path-input">Index single file by path</label>
            <div className="input-row">
              <input
                id="file-path-input"
                type="text"
                value={filePathInput}
                onChange={(e) => setFilePathInput(e.target.value)}
                placeholder="C:\path\to\document.md"
              />
              <button onClick={() => void handleIndexFile()} disabled={!filePathInput.trim()}>
                Index File
              </button>
            </div>
          </div>

          <div className="input-group">
            <label htmlFor="dir-path-input">Index directory</label>
            <div className="input-row">
              <input
                id="dir-path-input"
                type="text"
                value={dirPathInput}
                onChange={(e) => setDirPathInput(e.target.value)}
                placeholder="C:\path\to\notes_folder"
              />
              <button onClick={() => void handleIndexDirectory()} disabled={!dirPathInput.trim()}>
                Index Dir
              </button>
            </div>
            <label className="checkbox-label">
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
          <p className="card-desc">Test SQLite FTS5 lexical ranking combined with normalized subword vectors.</p>
          <div className="input-row">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSearch();
              }}
              placeholder="Query indexed knowledge..."
            />
            <button onClick={() => void handleSearch()} disabled={searching || !searchQuery.trim()}>
              {searching ? "Searching..." : "Search"}
            </button>
          </div>

          {searchResults.length > 0 && (
            <div className="search-results-list">
              <h4>Matches ({searchResults.length})</h4>
              {searchResults.map((res) => (
                <div className="search-result-item" key={res.citation_id}>
                  <div className="result-header">
                    <span className="citation-badge">{res.citation_id}</span>
                    <strong>{res.title}</strong>
                    <span className="result-score">RRF: {res.score}</span>
                  </div>
                  {res.start_line && (
                    <div className="result-lines">Lines {res.start_line}–{res.end_line}</div>
                  )}
                  <p className="result-snippet">{res.snippet}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right Column: Indexed Documents Catalog */}
        <div className="panel-card">
          <h3>Indexed Documents ({documents.length})</h3>
          <p className="card-desc">Persistent document metadata stored in SQLite knowledge index.</p>

          {documents.length === 0 ? (
            <div className="empty-state">
              <p>No documents indexed yet. Upload a file or index a folder to get started.</p>
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
            <div className="doc-inspector">
              <div className="inspector-header">
                <div>
                  <h4>Document: {selectedDoc.title}</h4>
                  <p className="inspector-path">{selectedDoc.file_path}</p>
                </div>
                <button className="btn-sm" onClick={() => setSelectedDoc(null)}>Close</button>
              </div>

              <h5>Indexed Chunks ({selectedDoc.chunks?.length || 0})</h5>
              <div className="chunks-list">
                {selectedDoc.chunks?.map((chunk) => (
                  <div className="chunk-card" key={chunk.id}>
                    <div className="chunk-meta">
                      <span>Chunk #{chunk.chunk_index + 1}</span>
                      <span>{chunk.token_count} tokens</span>
                      {chunk.start_line && <span>Lines {chunk.start_line}–{chunk.end_line}</span>}
                    </div>
                    <pre className="chunk-content"><code>{chunk.content}</code></pre>
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
