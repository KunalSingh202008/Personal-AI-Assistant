import { useState } from "react";

interface BrowserAgentViewProps {
  apiUrl: string;
}

interface PageData {
  url: string;
  status_code: number;
  title: string;
  description: string;
  text_preview: string;
  total_text_length: number;
  links_count: number;
  forms_count: number;
  links: { href: string; text: string }[];
  forms: { action: string; method: string; inputs: { name: string; type: string; placeholder: string }[] }[];
}

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

export default function BrowserAgentView({ apiUrl }: BrowserAgentViewProps) {
  const [urlInput, setUrlInput] = useState("https://fastapi.tiangolo.com");
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [pageData, setPageData] = useState<PageData | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);

  const handleNavigate = async (e?: React.FormEvent, directUrl?: string) => {
    if (e) e.preventDefault();
    const targetUrl = directUrl || urlInput;
    if (!targetUrl.trim()) return;

    setLoading(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiUrl}/api/browser/navigate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: targetUrl.trim() }),
      });
      const data = await res.json();
      if (data.success) {
        setPageData(data.page);
        setUrlInput(data.page.url);
      } else {
        setFeedback(`Navigation error: ${data.error || "Failed to load page"}`);
      }
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiUrl}/api/browser/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery.trim(), limit: 8 }),
      });
      const data = await res.json();
      setSearchResults(data.results || []);
      if (!data.results || data.results.length === 0) {
        setFeedback("No search results returned.");
      }
    } catch (err: unknown) {
      setFeedback(`Search error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="manager-view">
      <div className="manager-header">
        <div>
          <h2>Browser & Web Research Agent</h2>
          <p className="manager-subtitle">
            Autonomous web navigation, DOM distillation, link traversal, and live search engine querying.
          </p>
        </div>
      </div>

      {feedback && <div className="feedback-banner">{feedback}</div>}

      {/* Navigation URL Bar */}
      <form onSubmit={(e) => handleNavigate(e)} className="browser-toolbar">
        <input
          type="text"
          placeholder="https://example.com"
          value={urlInput}
          onChange={(e) => setUrlInput(e.target.value)}
          style={{ flex: 1 }}
        />
        <button type="submit" className="primary" disabled={loading || !urlInput.trim()}>
          {loading ? "Loading..." : "Navigate"}
        </button>
      </form>

      <div className="manager-grid">
        {/* Left: DOM Page Text & Structure */}
        <div className="manager-card" style={{ flex: 2 }}>
          {pageData ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                <h3>{pageData.title}</h3>
                <span className="badge-private">HTTP {pageData.status_code}</span>
              </div>
              <p style={{ fontSize: "0.85rem", color: "var(--accent)" }}>{pageData.url}</p>
              {pageData.description && (
                <p className="help-text" style={{ fontStyle: "italic" }}>
                  {pageData.description}
                </p>
              )}

              <hr style={{ margin: "12px 0", borderColor: "var(--border)" }} />

              <h4>Distilled Page Content ({pageData.total_text_length} chars)</h4>
              <div
                className="markdown-body"
                style={{
                  maxHeight: "360px",
                  overflowY: "auto",
                  padding: "12px",
                  background: "var(--bg-card)",
                  borderRadius: "6px",
                  fontSize: "0.85rem",
                  whiteSpace: "pre-wrap",
                }}
              >
                {pageData.text_preview}
              </div>

              {pageData.links.length > 0 && (
                <div style={{ marginTop: "16px" }}>
                  <h4>Discovered Page Links ({pageData.links_count})</h4>
                  <div style={{ maxHeight: "150px", overflowY: "auto", fontSize: "0.8rem" }}>
                    {pageData.links.slice(0, 15).map((l, idx) => (
                      <div key={idx} style={{ padding: "4px 0" }}>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => handleNavigate(undefined, l.href)}
                          style={{
                            background: "none",
                            border: "none",
                            color: "var(--accent)",
                            cursor: "pointer",
                            textAlign: "left",
                            padding: 0,
                          }}
                        >
                          🔗 {l.text || l.href}
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="help-text">Enter a website URL above to inspect and distill page text and structure.</p>
          )}
        </div>

        {/* Right: Live Web Search */}
        <div className="manager-card" style={{ flex: 1 }}>
          <h3>Search the Web</h3>
          <form onSubmit={handleSearch} className="form-group">
            <input
              type="text"
              placeholder="Search query..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <button type="submit" className="primary" disabled={loading || !searchQuery.trim()}>
              Search
            </button>
          </form>

          <div style={{ marginTop: "16px" }}>
            {searchResults.map((res, idx) => (
              <div key={idx} style={{ marginBottom: "12px", paddingBottom: "8px", borderBottom: "1px solid var(--border)" }}>
                <button
                  type="button"
                  className="link-button"
                  onClick={() => handleNavigate(undefined, res.url)}
                  style={{
                    background: "none",
                    border: "none",
                    fontWeight: 600,
                    color: "var(--accent)",
                    cursor: "pointer",
                    textAlign: "left",
                    padding: 0,
                  }}
                >
                  {res.title}
                </button>
                {res.snippet && <p style={{ fontSize: "0.8rem", color: "var(--text-muted)", margin: "4px 0" }}>{res.snippet}</p>}
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>{res.url}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
