import { useState, useEffect } from "react";

interface PCControlViewProps {
  apiUrl: string;
}

export default function PCControlView({ apiUrl }: PCControlViewProps) {
  const [metrics, setMetrics] = useState<any>(null);
  const [processes, setProcesses] = useState<any[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [screenshotPreview, setScreenshotPreview] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string>("");
  const [isLoading, setIsLoading] = useState(false);

  const fetchSystemData = async () => {
    try {
      const sysRes = await fetch(`${apiUrl}/api/pc/system`);
      if (sysRes.ok) {
        const sysData = await sysRes.json();
        setMetrics(sysData.metrics);
      }

      const procRes = await fetch(`${apiUrl}/api/pc/processes?limit=12`);
      if (procRes.ok) {
        const procData = await procRes.json();
        setProcesses(procData.processes || []);
      }
    } catch (e) {
      console.warn("Failed to fetch system data:", e);
    }
  };

  useEffect(() => {
    fetchSystemData();
    const interval = setInterval(fetchSystemData, 10000);
    return () => clearInterval(interval);
  }, [apiUrl]);

  const handleLaunch = async (app: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/pc/launch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app }),
      });
      const data = await res.json();
      setFeedback(data.message || `Launched ${app}`);
    } catch (e: any) {
      setFeedback(`Error: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClose = async (app: string) => {
    setIsLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/pc/close`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ app }),
      });
      const data = await res.json();
      setFeedback(data.message || `Closed ${app}`);
      fetchSystemData();
    } catch (e: any) {
      setFeedback(`Error: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleVolume = async (action: string, level?: number) => {
    try {
      const res = await fetch(`${apiUrl}/api/pc/volume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, level }),
      });
      const data = await res.json();
      setFeedback(data.message || `Volume action: ${action}`);
    } catch (e: any) {
      setFeedback(`Volume Error: ${e.message}`);
    }
  };

  const handleScreenshot = async () => {
    setIsLoading(true);
    setFeedback("Capturing desktop screenshot...");
    try {
      const res = await fetch(`${apiUrl}/api/pc/screenshot`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Screenshot capture failed");
      const data = await res.json();
      setScreenshotPreview(data.base64);
      setFeedback(`Screenshot saved to ${data.file_path} (${Math.round(data.size_bytes / 1024)} KB)`);
    } catch (e: any) {
      setFeedback(`Screenshot Error: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/pc/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery }),
      });
      const data = await res.json();
      setSearchResults(data.results || []);
      setFeedback(`Found ${data.results?.length || 0} files matching '${searchQuery}'`);
    } catch (e: any) {
      setFeedback(`Search Error: ${e.message}`);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="pc-control-view">
      <div className="pc-header">
        <h2>Windows PC Control Center</h2>
        <p>Real-time OS diagnostics, app management, audio levels, and local file operations.</p>
      </div>

      {feedback && (
        <div className="pc-feedback-banner">
          <span>{feedback}</span>
          <button onClick={() => setFeedback("")}>×</button>
        </div>
      )}

      {/* Hardware Monitors Grid */}
      <div className="pc-metrics-grid">
        <div className="metric-card">
          <div className="metric-title">CPU Load</div>
          <div className="metric-value">{metrics ? `${metrics.cpu_load_percent}%` : "--"}</div>
          <div className="metric-sub">AMD Ryzen 7 7735HS</div>
        </div>

        <div className="metric-card">
          <div className="metric-title">RAM Usage</div>
          <div className="metric-value">{metrics ? `${metrics.ram_usage_percent}%` : "--"}</div>
          <div className="metric-sub">
            {metrics ? `${metrics.used_ram_mb} MB used / ${metrics.free_ram_mb} MB free` : "--"}
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-title">Battery Status</div>
          <div className="metric-value">{metrics?.battery_percent !== null && metrics?.battery_percent !== undefined ? `${metrics.battery_percent}%` : "AC Power"}</div>
          <div className="metric-sub">
            {metrics?.battery_status === 2 ? "Plugged in / Charging" : "Running on battery"}
          </div>
        </div>

        <div className="metric-card">
          <div className="metric-title">Master Volume</div>
          <div className="volume-actions">
            <button onClick={() => handleVolume("up")}>🔊 Up</button>
            <button onClick={() => handleVolume("down")}>🔉 Down</button>
            <button onClick={() => handleVolume("mute")}>🔇 Mute</button>
          </div>
          <div className="volume-slider-row">
            <button onClick={() => handleVolume("set", 25)}>25%</button>
            <button onClick={() => handleVolume("set", 50)}>50%</button>
            <button onClick={() => handleVolume("set", 75)}>75%</button>
            <button onClick={() => handleVolume("set", 100)}>100%</button>
          </div>
        </div>
      </div>

      {/* Two Column Layout: App Launcher & Screenshot / File Search */}
      <div className="pc-sections-grid">
        {/* App Launcher */}
        <div className="pc-card">
          <h3>Application Launcher</h3>
          <p>Quickly start or terminate desktop applications.</p>
          <div className="app-buttons-grid">
            <div className="app-item">
              <span>Google Chrome</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("chrome")}>Open</button>
                <button className="close-btn" onClick={() => handleClose("chrome")}>Close</button>
              </div>
            </div>
            <div className="app-item">
              <span>VS Code</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("code")}>Open</button>
                <button className="close-btn" onClick={() => handleClose("code")}>Close</button>
              </div>
            </div>
            <div className="app-item">
              <span>Notepad</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("notepad")}>Open</button>
                <button className="close-btn" onClick={() => handleClose("notepad")}>Close</button>
              </div>
            </div>
            <div className="app-item">
              <span>Calculator</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("calc")}>Open</button>
                <button className="close-btn" onClick={() => handleClose("calc")}>Close</button>
              </div>
            </div>
            <div className="app-item">
              <span>Spotify</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("spotify")}>Open</button>
                <button className="close-btn" onClick={() => handleClose("spotify")}>Close</button>
              </div>
            </div>
            <div className="app-item">
              <span>File Explorer</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("explorer")}>Open</button>
              </div>
            </div>
            <div className="app-item">
              <span>Task Manager</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("taskmgr")}>Open</button>
              </div>
            </div>
            <div className="app-item">
              <span>MS Paint</span>
              <div className="app-actions">
                <button className="launch-btn" onClick={() => handleLaunch("mspaint")}>Open</button>
              </div>
            </div>
          </div>
        </div>

        {/* Screenshot & Screen Intelligence */}
        <div className="pc-card">
          <div className="card-top-flex">
            <h3>Desktop Screenshot Intelligence</h3>
            <button className="primary-action-btn" onClick={handleScreenshot} disabled={isLoading}>
              📸 Capture Primary Screen
            </button>
          </div>
          {screenshotPreview ? (
            <div className="screenshot-preview-container">
              <img src={screenshotPreview} alt="Desktop Preview" className="screenshot-img" />
            </div>
          ) : (
            <div className="screenshot-empty-state">
              <span>Click "Capture Primary Screen" to grab a high-resolution snapshot.</span>
            </div>
          )}
        </div>
      </div>

      {/* Fast Local File Search */}
      <div className="pc-card">
        <h3>Fast Local File Search</h3>
        <p>Instant scan across Documents, Downloads, and Desktop directories.</p>
        <form onSubmit={handleSearch} className="file-search-form">
          <input
            type="text"
            placeholder="Search files by name or extension (e.g. .pdf, project, report)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
          />
          <button type="submit" className="search-btn" disabled={isLoading}>
            Search
          </button>
        </form>

        {searchResults.length > 0 && (
          <div className="search-results-table">
            <div className="table-header">
              <span>Name</span>
              <span>Folder</span>
              <span>Size</span>
              <span>Path</span>
            </div>
            {searchResults.map((item, idx) => (
              <div key={idx} className="table-row">
                <span className="file-name">{item.name}</span>
                <span className="file-folder">{item.folder}</span>
                <span className="file-size">{Math.round(item.size_bytes / 1024)} KB</span>
                <span className="file-path" title={item.path}>{item.path}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Top Running Processes */}
      <div className="pc-card">
        <h3>Top Memory Consuming Processes</h3>
        <div className="process-list-grid">
          {processes.map((proc, idx) => (
            <div key={idx} className="process-pill">
              <span className="proc-name">{proc.ProcessName}</span>
              <span className="proc-mem">{proc.MemoryMB} MB</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
