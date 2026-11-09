import { useCallback, useEffect, useState } from "react";

interface GitHubManagerProps {
  apiUrl: string;
}

interface GitHubUser {
  authenticated: boolean;
  login?: string;
  name?: string;
  avatar_url?: string;
  public_repos?: number;
  total_private_repos?: number;
  error?: string;
}

interface WorkspaceGitStatus {
  is_git: boolean;
  path?: string;
  current_branch?: string;
  clean?: boolean;
  staged_files?: { path: string; status: string }[];
  modified_files?: { path: string; status: string }[];
  untracked_files?: string[];
  error?: string;
}

interface Repository {
  id: number;
  name: string;
  full_name: string;
  owner: string;
  description: string;
  private: boolean;
  html_url: string;
  clone_url: string;
  default_branch: string;
  stargazers_count: number;
  language: string;
  updated_at: string;
}

export default function GitHubManager({ apiUrl }: GitHubManagerProps) {
  const [tokenInput, setTokenInput] = useState("");
  const [authStatus, setAuthStatus] = useState<GitHubUser | null>(null);
  const [gitStatus, setGitStatus] = useState<WorkspaceGitStatus | null>(null);
  const [repos, setRepos] = useState<Repository[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  // Commit / Push form
  const [commitMessage, setCommitMessage] = useState("");

  // Create repo form
  const [newRepoName, setNewRepoName] = useState("");
  const [newRepoDesc, setNewRepoDesc] = useState("");
  const [newRepoPrivate, setNewRepoPrivate] = useState(true);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/github/status`);
      if (res.ok) {
        const data = await res.json();
        setAuthStatus(data.github_auth);
        setGitStatus(data.workspace_git);
      }
    } catch {
      setFeedback("Failed to connect to backend GitHub service.");
    }
  }, [apiUrl]);

  const fetchRepos = useCallback(async (query: string = "") => {
    setLoading(true);
    try {
      const url = query.trim()
        ? `${apiUrl}/api/github/repos?search=${encodeURIComponent(query.trim())}`
        : `${apiUrl}/api/github/repos`;
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setRepos(data);
      } else {
        setRepos([]);
      }
    } catch {
      setFeedback("Failed to fetch repositories.");
    } finally {
      setLoading(false);
    }
  }, [apiUrl]);

  useEffect(() => {
    let active = true;
    const init = async () => {
      try {
        const res = await fetch(`${apiUrl}/api/github/status`);
        if (res.ok && active) {
          const data = await res.json();
          setAuthStatus(data.github_auth);
          setGitStatus(data.workspace_git);
          if (data.github_auth?.authenticated) {
            const reposRes = await fetch(`${apiUrl}/api/github/repos`);
            if (reposRes.ok && active) {
              const reposData = await reposRes.json();
              setRepos(reposData);
            }
          }
        }
      } catch {
        if (active) setFeedback("Failed to connect to backend GitHub service.");
      }
    };
    void init();
    return () => {
      active = false;
    };
  }, [apiUrl]);

  const handleConnectToken = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!tokenInput.trim()) return;
    setLoading(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiUrl}/api/github/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: tokenInput.trim() }),
      });
      const data = await res.json();
      if (data.authenticated) {
        setAuthStatus(data);
        setTokenInput("");
        setFeedback(`Connected successfully as @${data.login}!`);
        fetchRepos();
      } else {
        setFeedback(`Authentication failed: ${data.error || "Invalid token"}`);
      }
    } catch (err: unknown) {
      setFeedback(`Error connecting: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    if (!window.confirm("Are you sure you want to disconnect GitHub?")) return;
    try {
      await fetch(`${apiUrl}/api/github/token`, { method: "DELETE" });
      setAuthStatus(null);
      setRepos([]);
      setFeedback("Disconnected GitHub account.");
      fetchStatus();
    } catch {
      setFeedback("Error disconnecting account.");
    }
  };

  const handleCommit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!commitMessage.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/github/commit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: commitMessage.trim() }),
      });
      const data = await res.json();
      if (data.success) {
        setFeedback(`Committed [${data.commit_sha || "OK"}]: ${commitMessage}`);
        setCommitMessage("");
        fetchStatus();
      } else {
        setFeedback(`Commit failed: ${data.error}`);
      }
    } catch {
      setFeedback("Commit request failed.");
    } finally {
      setLoading(false);
    }
  };

  const handlePush = async () => {
    if (!window.confirm("Push local commits to remote repository?")) return;
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/github/push`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ remote: "origin" }),
      });
      const data = await res.json();
      if (data.success) {
        setFeedback(`Pushed successfully to origin/${data.branch}!`);
        fetchStatus();
      } else {
        setFeedback(`Push failed: ${data.error}`);
      }
    } catch {
      setFeedback("Push request failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateRepo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRepoName.trim()) return;
    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/github/create-repo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newRepoName.trim(),
          description: newRepoDesc.trim(),
          private: newRepoPrivate,
          auto_init: true,
        }),
      });
      const data = await res.json();
      if (data.name) {
        setFeedback(`Created repository ${data.full_name} on GitHub!`);
        setNewRepoName("");
        setNewRepoDesc("");
        fetchRepos();
      } else {
        setFeedback(`Failed to create repository: ${JSON.stringify(data)}`);
      }
    } catch {
      setFeedback("Failed to create repository.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="manager-view">
      <div className="manager-header">
        <div>
          <h2>GitHub Integration & Repository Operations</h2>
          <p className="manager-subtitle">
            Autonomous repository discovery, code inspection, commit creation, and remote push.
          </p>
        </div>
        {authStatus?.authenticated && (
          <div className="auth-pill">
            {authStatus.avatar_url && (
              <img src={authStatus.avatar_url} alt="GitHub avatar" className="avatar-img" />
            )}
            <span>@{authStatus.login}</span>
            <button className="btn-small danger" onClick={handleDisconnect}>
              Disconnect
            </button>
          </div>
        )}
      </div>

      {feedback && <div className="feedback-banner">{feedback}</div>}

      <div className="manager-grid">
        {/* Left Column: Account & Workspace Status */}
        <div className="manager-card">
          <h3>Authentication & Workspace Git</h3>
          {!authStatus?.authenticated ? (
            <form onSubmit={handleConnectToken} className="form-group">
              <p className="help-text">
                Enter your GitHub Personal Access Token (classic with <code>repo</code> scope or fine-grained) to enable repository access.
              </p>
              <input
                type="password"
                placeholder="ghp_xxxxxxxxxxxx"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                required
              />
              <button type="submit" className="primary" disabled={loading}>
                {loading ? "Connecting..." : "Connect GitHub Account"}
              </button>
            </form>
          ) : (
            <div className="info-block">
              <p>
                <strong>Connected Account:</strong> {authStatus.name || authStatus.login} (@{authStatus.login})
              </p>
              <p>
                <strong>Public Repositories:</strong> {authStatus.public_repos} | <strong>Private:</strong> {authStatus.total_private_repos}
              </p>
            </div>
          )}

          <hr style={{ margin: "16px 0", borderColor: "var(--border)" }} />

          <h4>Workspace Git Status</h4>
          {gitStatus?.is_git ? (
            <div className="info-block">
              <p>
                <strong>Branch:</strong> <code>{gitStatus.current_branch}</code> | <strong>Status:</strong>{" "}
                <span className={gitStatus.clean ? "tag-clean" : "tag-dirty"}>
                  {gitStatus.clean ? "Working Tree Clean" : "Modified Files Present"}
                </span>
              </p>
              {gitStatus.modified_files && gitStatus.modified_files.length > 0 && (
                <p>
                  <strong>Modified:</strong> {gitStatus.modified_files.map((f) => f.path).join(", ")}
                </p>
              )}
              {gitStatus.untracked_files && gitStatus.untracked_files.length > 0 && (
                <p>
                  <strong>Untracked:</strong> {gitStatus.untracked_files.join(", ")}
                </p>
              )}

              {/* Commit form */}
              <form onSubmit={handleCommit} className="form-group" style={{ marginTop: "12px" }}>
                <input
                  type="text"
                  placeholder="Commit message..."
                  value={commitMessage}
                  onChange={(e) => setCommitMessage(e.target.value)}
                />
                <div style={{ display: "flex", gap: "8px" }}>
                  <button type="submit" className="primary" disabled={loading || !commitMessage.trim()}>
                    Commit Changes
                  </button>
                  <button type="button" className="btn-secondary" onClick={handlePush} disabled={loading}>
                    Push to Origin
                  </button>
                </div>
              </form>
            </div>
          ) : (
            <p className="help-text">Workspace is not currently a git repository or git status is unavailable.</p>
          )}
        </div>

        {/* Right Column: Repositories & Creation */}
        <div className="manager-card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3>Your Repositories</h3>
            {authStatus?.authenticated && (
              <button className="btn-small" onClick={() => fetchRepos(searchQuery)} disabled={loading}>
                Refresh
              </button>
            )}
          </div>

          {authStatus?.authenticated ? (
            <>
              <input
                type="text"
                placeholder="Search repositories..."
                value={searchQuery}
                onChange={(e) => {
                  setSearchQuery(e.target.value);
                  fetchRepos(e.target.value);
                }}
                style={{ marginBottom: "12px" }}
              />

              <div className="repo-list">
                {repos.length === 0 ? (
                  <p className="help-text">{loading ? "Loading repositories..." : "No repositories found."}</p>
                ) : (
                  repos.map((repo) => (
                    <div key={repo.id} className="repo-item">
                      <div className="repo-title">
                        <a href={repo.html_url} target="_blank" rel="noreferrer">
                          {repo.full_name}
                        </a>
                        {repo.private && <span className="badge-private">Private</span>}
                      </div>
                      {repo.description && <p className="repo-desc">{repo.description}</p>}
                      <div className="repo-meta">
                        {repo.language && <span>{repo.language}</span>}
                        <span>Branch: {repo.default_branch}</span>
                        <span>⭐ {repo.stargazers_count}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>

              <hr style={{ margin: "16px 0", borderColor: "var(--border)" }} />

              <h4>Create New GitHub Repository</h4>
              <form onSubmit={handleCreateRepo} className="form-group">
                <input
                  type="text"
                  placeholder="Repository name..."
                  value={newRepoName}
                  onChange={(e) => setNewRepoName(e.target.value)}
                  required
                />
                <input
                  type="text"
                  placeholder="Description (optional)..."
                  value={newRepoDesc}
                  onChange={(e) => setNewRepoDesc(e.target.value)}
                />
                <label style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "0.85rem" }}>
                  <input
                    type="checkbox"
                    checked={newRepoPrivate}
                    onChange={(e) => setNewRepoPrivate(e.target.checked)}
                  />
                  Make repository private
                </label>
                <button type="submit" className="primary" disabled={loading || !newRepoName.trim()}>
                  Create Repository on GitHub
                </button>
              </form>
            </>
          ) : (
            <p className="help-text">Connect your GitHub Personal Access Token on the left to browse and manage repositories.</p>
          )}
        </div>
      </div>
    </div>
  );
}
