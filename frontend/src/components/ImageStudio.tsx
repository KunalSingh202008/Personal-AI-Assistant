import { useCallback, useEffect, useState } from "react";

interface ImageStudioProps {
  apiUrl: string;
}

interface ImageRecord {
  id: string;
  filename: string;
  file_path: string;
  format: string;
  backend: string;
  prompt: string;
  width: number;
  height: number;
  created_at: string;
  svg_preview?: string;
}

export default function ImageStudio({ apiUrl }: ImageStudioProps) {
  const [activeSubTab, setActiveSubTab] = useState<"generate" | "vision" | "gallery">("generate");

  // Image Gen State
  const [prompt, setPrompt] = useState("");
  const [width, setWidth] = useState(800);
  const [height, setHeight] = useState(600);
  const [generating, setGenerating] = useState(false);
  const [latestImage, setLatestImage] = useState<ImageRecord | null>(null);
  const [gallery, setGallery] = useState<ImageRecord[]>([]);

  // Vision State
  const [visionPrompt, setVisionPrompt] = useState("Describe what you see in this image in detail.");
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [visionAnalysis, setVisionAnalysis] = useState<string | null>(null);
  const [detectedModels, setDetectedModels] = useState<string[]>([]);

  // Feedback
  const [feedback, setFeedback] = useState<string | null>(null);

  const fetchGallery = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/image-gen/gallery`);
      if (res.ok) {
        const data = await res.json();
        setGallery(data);
      }
    } catch {
      // silent
    }
  }, [apiUrl]);

  useEffect(() => {
    let active = true;
    const init = async () => {
      try {
        const [galRes, visRes] = await Promise.all([
          fetch(`${apiUrl}/api/image-gen/gallery`),
          fetch(`${apiUrl}/api/vision/models`),
        ]);
        if (galRes.ok && active) {
          const data = await galRes.json();
          setGallery(data);
        }
        if (visRes.ok && active) {
          const data = await visRes.json();
          setDetectedModels(data.models || []);
        }
      } catch {
        // silent
      }
    };
    void init();
    return () => {
      active = false;
    };
  }, [apiUrl]);

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;
    setGenerating(true);
    setFeedback(null);
    try {
      const res = await fetch(`${apiUrl}/api/image-gen/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: prompt.trim(), width, height }),
      });
      const data = await res.json();
      if (data.success) {
        setLatestImage(data.image);
        setFeedback(data.message || "Image generated successfully!");
        fetchGallery();
      } else {
        setFeedback(`Generation failed: ${data.error || "Unknown error"}`);
      }
    } catch (err: unknown) {
      setFeedback(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setGenerating(false);
    }
  };

  const handleImageUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setImagePreview(event.target?.result as string);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleAnalyzeVision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!imagePreview) {
      setFeedback("Please select an image file first.");
      return;
    }
    setAnalyzing(true);
    setVisionAnalysis(null);
    setFeedback(null);

    try {
      // Extract base64 without header
      const base64Data = imagePreview.includes(",") ? imagePreview.split(",")[1] : imagePreview;
      const res = await fetch(`${apiUrl}/api/vision/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          image_base64: base64Data,
          prompt: visionPrompt.trim(),
        }),
      });
      const data = await res.json();
      if (data.analysis) {
        setVisionAnalysis(data.analysis);
      } else {
        setFeedback(data.error || "Vision analysis failed.");
      }
    } catch (err: unknown) {
      setFeedback(`Analysis error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDeleteImage = async (id: string) => {
    if (!window.confirm("Delete this image from gallery?")) return;
    try {
      const res = await fetch(`${apiUrl}/api/image-gen/gallery/${id}`, { method: "DELETE" });
      if (res.ok) {
        setGallery((prev) => prev.filter((img) => img.id !== id));
        if (latestImage?.id === id) setLatestImage(null);
      }
    } catch {
      setFeedback("Failed to delete image.");
    }
  };

  return (
    <div className="manager-view">
      <div className="manager-header">
        <div>
          <h2>Image & Multimodal Vision Studio</h2>
          <p className="manager-subtitle">
            Generate graphics, inspect screenshots, and understand visual diagrams with local AI models.
          </p>
        </div>
        <div className="subtab-buttons">
          <button
            className={`btn-small ${activeSubTab === "generate" ? "active" : ""}`}
            onClick={() => setActiveSubTab("generate")}
          >
            Image Generation
          </button>
          <button
            className={`btn-small ${activeSubTab === "vision" ? "active" : ""}`}
            onClick={() => setActiveSubTab("vision")}
          >
            Vision Inspector
          </button>
          <button
            className={`btn-small ${activeSubTab === "gallery" ? "active" : ""}`}
            onClick={() => setActiveSubTab("gallery")}
          >
            Gallery ({gallery.length})
          </button>
        </div>
      </div>

      {feedback && <div className="feedback-banner">{feedback}</div>}

      {/* GENERATE TAB */}
      {activeSubTab === "generate" && (
        <div className="manager-grid">
          <div className="manager-card">
            <h3>Generate Image or Diagram</h3>
            <form onSubmit={handleGenerate} className="form-group">
              <label>Prompt:</label>
              <textarea
                rows={4}
                placeholder="e.g. Microservices architecture with Kafka event bus, or Cyberpunk assistant logo..."
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
              />
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                <div>
                  <label>Width (px):</label>
                  <input
                    type="number"
                    value={width}
                    onChange={(e) => setWidth(Number(e.target.value))}
                    min={256}
                    max={1920}
                  />
                </div>
                <div>
                  <label>Height (px):</label>
                  <input
                    type="number"
                    value={height}
                    onChange={(e) => setHeight(Number(e.target.value))}
                    min={256}
                    max={1920}
                  />
                </div>
              </div>
              <button type="submit" className="primary" disabled={generating || !prompt.trim()}>
                {generating ? "Synthesizing Image..." : "Generate Image"}
              </button>
            </form>
          </div>

          <div className="manager-card">
            <h3>Preview & Output</h3>
            {latestImage ? (
              <div className="image-preview-container">
                {latestImage.svg_preview ? (
                  <div
                    dangerouslySetInnerHTML={{ __html: latestImage.svg_preview }}
                    style={{ maxWidth: "100%", borderRadius: "8px", overflow: "hidden" }}
                  />
                ) : (
                  <img
                    src={`${apiUrl}/${latestImage.file_path}`}
                    alt={latestImage.prompt}
                    style={{ maxWidth: "100%", borderRadius: "8px" }}
                  />
                )}
                <div style={{ marginTop: "12px", fontSize: "0.85rem", color: "var(--text-muted)" }}>
                  <p><strong>Prompt:</strong> {latestImage.prompt}</p>
                  <p><strong>Format:</strong> {latestImage.format} | <strong>Backend:</strong> {latestImage.backend}</p>
                  <p><strong>Saved:</strong> <code>{latestImage.file_path}</code></p>
                </div>
              </div>
            ) : (
              <p className="help-text">Enter a prompt on the left to generate diagrams, charts, and illustrations.</p>
            )}
          </div>
        </div>
      )}

      {/* VISION TAB */}
      {activeSubTab === "vision" && (
        <div className="manager-grid">
          <div className="manager-card">
            <h3>Analyze Image or Screenshot</h3>
            <p className="help-text">
              Active Vision Models in Ollama:{" "}
              {detectedModels.length > 0 ? (
                <code>{detectedModels.join(", ")}</code>
              ) : (
                <span style={{ color: "var(--accent-warn)" }}>None detected (ollama pull llava to enable neural vision)</span>
              )}
            </p>
            <form onSubmit={handleAnalyzeVision} className="form-group">
              <input type="file" accept="image/*" onChange={handleImageUpload} />
              {imagePreview && (
                <div style={{ marginTop: "12px" }}>
                  <img
                    src={imagePreview}
                    alt="Upload Preview"
                    style={{ maxHeight: "200px", maxWidth: "100%", borderRadius: "6px" }}
                  />
                </div>
              )}
              <label>Instruction / Question:</label>
              <input
                type="text"
                value={visionPrompt}
                onChange={(e) => setVisionPrompt(e.target.value)}
                placeholder="What is happening in this image?"
              />
              <button type="submit" className="primary" disabled={analyzing || !imagePreview}>
                {analyzing ? "Analyzing Visual Content..." : "Inspect Image"}
              </button>
            </form>
          </div>

          <div className="manager-card">
            <h3>Vision Findings & Breakdown</h3>
            {visionAnalysis ? (
              <div className="markdown-body" style={{ whiteSpace: "pre-wrap", fontSize: "0.9rem" }}>
                {visionAnalysis}
              </div>
            ) : (
              <p className="help-text">Upload an image or screenshot on the left and submit to view AI analysis.</p>
            )}
          </div>
        </div>
      )}

      {/* GALLERY TAB */}
      {activeSubTab === "gallery" && (
        <div className="manager-card">
          <h3>Generated Images Gallery</h3>
          {gallery.length === 0 ? (
            <p className="help-text">No images generated yet.</p>
          ) : (
            <div className="gallery-grid">
              {gallery.map((img) => (
                <div key={img.id} className="gallery-card">
                  {img.svg_preview ? (
                    <div
                      dangerouslySetInnerHTML={{ __html: img.svg_preview }}
                      style={{ width: "100%", height: "180px", overflow: "hidden", borderRadius: "6px" }}
                    />
                  ) : (
                    <div className="gallery-thumb-placeholder">{img.filename}</div>
                  )}
                  <div className="gallery-info">
                    <p className="gallery-prompt">{img.prompt}</p>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px" }}>
                      <span className="badge-private">{img.format}</span>
                      <button className="btn-small danger" onClick={() => handleDeleteImage(img.id)}>
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
