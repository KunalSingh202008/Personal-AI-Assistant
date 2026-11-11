import { useCallback, useEffect, useRef, useState } from "react";
import type { ChangeEvent, ReactNode } from "react";
import "./App.css";
import StudentTasksPanel from "./StudentTasks";
import KnowledgeManager from "./components/KnowledgeManager";
import DatabaseConnectors from "./components/DatabaseConnectors";
import MemoryManager from "./components/MemoryManager";
import SettingsView from "./components/SettingsView";
import GitHubManager from "./components/GitHubManager";
import ImageStudio from "./components/ImageStudio";
import BrowserAgentView from "./components/BrowserAgentView";
import VoiceAssistant from "./components/VoiceAssistant";
import PCControlView from "./components/PCControlView";
import { sanitizeMessagePayload } from "./messageUtils";
import type { AgentTaskView, Approval, Conversation, Message } from "./types";

type AppTab =
  | "voice"
  | "chat"
  | "pc"
  | "github"
  | "imageStudio"
  | "browserAgent"
  | "knowledge"
  | "connectors"
  | "memory"
  | "settings";
type AssistantMode = "chat" | "research" | "agent";
type ResearchDepth = "quick" | "standard" | "deep";

type StreamEvent = {
  type?: string;
  token?: string;
  content?: string;
  conversation_id?: number;
  error?: string;
  steps?: string[];
  step?: string | number;
  tool?: string;
  output?: string;
  approval_id?: string;
  action?: string;
  detail?: string;
  diff?: string;
  action_digest?: string;
  risk?: "GREEN" | "AMBER" | "RED";
  purpose?: string;
  resource?: string;
  reversible?: boolean;
  alternatives?: string;
  done?: boolean;
  message?: string;
  task_id?: string;
  state?: string;
  status?: string;
  path?: string;
  sources?: { citation_id: string; title: string; path: string; snippet: string; score: number }[];
};

let activeApiUrl = (() => {
  const saved = localStorage.getItem("nexus_api_url");
  if (saved && !saved.includes(":8000")) return saved;
  return "http://127.0.0.1:8001";
})();

async function detectNexusBackend(): Promise<string> {
  const saved = localStorage.getItem("nexus_api_url");
  const candidates = [
    saved && !saved.includes(":8000") ? saved : null,
    "http://127.0.0.1:8001",
    "http://127.0.0.1:8002",
    "http://127.0.0.1:8080",
    "http://127.0.0.1:8000",
  ].filter(Boolean) as string[];

  const unique = Array.from(new Set(candidates));

  for (const url of unique) {
    try {
      const res = await fetch(`${url}/api/health`, {
        headers: { Accept: "application/json" },
        signal: AbortSignal.timeout(1500),
      });
      if (res.ok) {
        const data = await res.json();
        if (
          data &&
          typeof data === "object" &&
          data.service !== "CampusConnect API" &&
          ("nexus" in data || data.service === "Nexus AI" || "model_installed" in data)
        ) {
          localStorage.setItem("nexus_api_url", url);
          activeApiUrl = url;
          return url;
        }
      }
    } catch {
      // try next
    }
  }
  return "http://127.0.0.1:8001";
}

function safeText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || value === null) return String(value);
  if (Array.isArray(value)) return value.map((item) => safeText(item)).join(", ");
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return Object.prototype.toString.call(value);
    }
  }
  return String(value);
}

function errorText(value: unknown, fallback: string): string {
  if (value instanceof Error) return value.message || fallback;
  if (typeof value === "string") return value.trim() || fallback;
  const rendered = safeText(value);
  return rendered && rendered !== "[object Object]" ? rendered : fallback;
}

function inlineMarkdown(text: string, prefix: string): ReactNode[] {
  const pieces = text.split(
    /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g,
  );
  return pieces.map((piece, index) => {
    const key = `${prefix}-${index}`;
    if (piece.startsWith("`") && piece.endsWith("`")) {
      return <code key={key}>{piece.slice(1, -1)}</code>;
    }
    if (piece.startsWith("**") && piece.endsWith("**")) {
      return <strong key={key}>{piece.slice(2, -2)}</strong>;
    }
    if (piece.startsWith("*") && piece.endsWith("*")) {
      return <em key={key}>{piece.slice(1, -1)}</em>;
    }
    const link = piece.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (link) {
      let href: URL | undefined;
      try {
        href = new URL(link[2], window.location.href);
      } catch {
        href = undefined;
      }
      if (href && ["http:", "https:", "mailto:"].includes(href.protocol)) {
        return (
          <a key={key} href={href.href} target="_blank" rel="noreferrer">
            {link[1]}
          </a>
        );
      }
      return link[1];
    }
    return piece;
  });
}

function highlightCode(code: string): ReactNode[] {
  const tokenPattern =
    /(\/\/[^\n]*|#[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b(?:const|let|var|function|return|if|else|for|while|class|new|async|await|import|from|export|default|def|print|true|false|null|None|True|False|try|except|raise|with|as|public|private|static|void|int|string|boolean)\b|\b\d+(?:\.\d+)?\b)/g;
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = tokenPattern.exec(code)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(code.slice(lastIndex, match.index));
    }
    const token = match[0];
    let className: string;
    if (token.startsWith("//") || token.startsWith("#") || token.startsWith("/*")) {
      className = "token-comment";
    } else if (token.startsWith('"') || token.startsWith("'") || token.startsWith("`")) {
      className = "token-string";
    } else if (/^\d/.test(token)) {
      className = "token-number";
    } else {
      className = "token-keyword";
    }
    nodes.push(
      <span className={className} key={`${match.index}-${token.slice(0, 10)}`}>
        {token}
      </span>,
    );
    lastIndex = match.index + token.length;
  }
  if (lastIndex < code.length) {
    nodes.push(code.slice(lastIndex));
  }
  return nodes;
}

function Markdown({ content }: { content: string }) {
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const copyCode = (codeText: string, index: number) => {
    void navigator.clipboard.writeText(codeText);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const lines = content.split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let listItems: string[] = [];
  let fenced = false;
  let code: string[] = [];
  let language = "";
  let blockIndex = 0;

  const flushParagraph = () => {
    if (paragraph.length) {
      const text = paragraph.join("\n");
      blocks.push(
        <p key={`p-${blocks.length}`}>{inlineMarkdown(text, `p-${blocks.length}`)}</p>,
      );
      paragraph = [];
    }
  };

  const flushList = () => {
    if (listItems.length) {
      blocks.push(
        <ul key={`ul-${blocks.length}`}>
          {listItems.map((item, index) => (
            <li key={`li-${blocks.length}-${index}`}>
              {inlineMarkdown(item, `li-${blocks.length}-${index}`)}
            </li>
          ))}
        </ul>,
      );
      listItems = [];
    }
  };

  lines.forEach((line) => {
    const fenceMatch = line.match(/^```([a-zA-Z0-9_-]+)?/);
    if (fenceMatch) {
      if (fenced) {
        const fullCode = code.join("\n");
        const currentIndex = blockIndex++;
        blocks.push(
          <div className="code-block" key={`code-${currentIndex}`}>
            <div className="code-toolbar">
              <span>{language || "code"}</span>
              <button
                className="copy-btn"
                onClick={() => copyCode(fullCode, currentIndex)}
              >
                {copiedIndex === currentIndex ? "Copied!" : "Copy"}
              </button>
            </div>
            <pre><code>{highlightCode(fullCode)}</code></pre>
          </div>,
        );
        code = [];
        fenced = false;
      } else {
        flushList();
        flushParagraph();
        fenced = true;
        language = fenceMatch[1] ?? "";
      }
      return;
    }

    if (fenced) {
      code.push(line);
      return;
    }

    const listMatch = line.match(/^[-*]\s+(.*)$/);
    if (listMatch) {
      flushParagraph();
      listItems.push(listMatch[1]);
      return;
    }
    if (listItems.length) {
      flushList();
    }

    if (!line.trim()) {
      flushParagraph();
      return;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushParagraph();
      const depth = heading[1].length;
      const headingContent = inlineMarkdown(heading[2], `h-${blocks.length}`);
      blocks.push(
        depth <= 2
          ? depth === 1
            ? <h2 key={`h-${blocks.length}`}>{headingContent}</h2>
            : <h3 key={`h-${blocks.length}`}>{headingContent}</h3>
          : <h4 key={`h-${blocks.length}`}>{headingContent}</h4>,
      );
      return;
    }
    paragraph.push(line);
  });

  if (fenced) {
    const fullCode = code.join("\n");
    const currentIndex = blockIndex++;
    blocks.push(
      <div className="code-block" key={`code-${currentIndex}`}>
        <div className="code-toolbar"><span>{language || "code"}</span></div>
        <pre><code>{highlightCode(fullCode)}</code></pre>
      </div>,
    );
  }
  flushList();
  flushParagraph();
  return <div className="markdown-body">{blocks}</div>;
}

async function readResponseError(response: Response): Promise<string> {
  try {
    const data = await response.json() as unknown;
    const detail = typeof data === "object" && data !== null && "detail" in data
      ? (data as { detail?: unknown }).detail
      : data;
    return errorText(detail, `Request failed (${response.status})`);
  } catch {
    return `Request failed (${response.status})`;
  }
}

export default function App() {
  const [activeTab, setActiveTab] = useState<AppTab>("voice");
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [apiUrl, setApiUrl] = useState<string>(activeApiUrl);

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationSearch, setConversationSearch] = useState("");
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [modelStatus, setModelStatus] = useState("Checking model...");
  const [mode, setMode] = useState<AssistantMode>("chat");
  const [researchDepth, setResearchDepth] = useState<ResearchDepth>("standard");
  const [researchSources, setResearchSources] = useState<{ citation_id: string; title: string; path: string; snippet: string; score: number }[]>([]);
  const [attachedFiles, setAttachedFiles] = useState<string[]>([]);

  const [workspace, setWorkspace] = useState("");
  const [workspaceInput, setWorkspaceInput] = useState("");
  const [projectContext, setProjectContext] = useState("");
  const [projectContextDraft, setProjectContextDraft] = useState("");
  const [projectContextReady, setProjectContextReady] = useState(false);
  const [projectContextSaving, setProjectContextSaving] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
  const [agentTask, setAgentTask] = useState<AgentTaskView | null>(null);
  const [approval, setApproval] = useState<Approval | null>(null);
  const [retryTurnId, setRetryTurnId] = useState<string | null>(null);
  const [autonomyLevel, setAutonomyLevel] = useState<number>(3);

  const fetchAutonomy = useCallback(async () => {
    try {
      const res = await fetch(`${apiUrl}/api/orchestrator/autonomy`);
      if (res.ok) {
        const data = await res.json();
        setAutonomyLevel(data.level);
      }
    } catch {
      // silent
    }
  }, [apiUrl]);

  const changeAutonomy = async (newLevel: number) => {
    setAutonomyLevel(newLevel);
    try {
      await fetch(`${apiUrl}/api/orchestrator/autonomy`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ level: newLevel }),
      });
    } catch {
      // silent
    }
  };

  const activeRequest = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
  };

  const refreshConversations = useCallback(async () => {
    const response = await fetch(`${apiUrl}/api/conversations`);
    if (!response.ok) throw new Error(await readResponseError(response));
    setConversations(await response.json() as Conversation[]);
  }, [apiUrl]);

  useEffect(() => {
    let active = true;
    const initialize = async () => {
      const resolvedBackend = await detectNexusBackend();
      if (!active) return;
      setApiUrl(resolvedBackend);

      const [
        healthResponse,
        conversationsResponse,
        workspaceResponse,
        contextResponse,
      ] =
        await Promise.all([
          fetch(`${resolvedBackend}/api/health`),
          fetch(`${resolvedBackend}/api/conversations`),
          fetch(`${resolvedBackend}/api/workspace`),
          fetch(`${resolvedBackend}/api/workspace/context`),
        ]);
      if (!healthResponse.ok) throw new Error(await readResponseError(healthResponse));
      if (!conversationsResponse.ok) {
        throw new Error(await readResponseError(conversationsResponse));
      }
      if (!workspaceResponse.ok) {
        throw new Error(await readResponseError(workspaceResponse));
      }
      if (!contextResponse.ok) {
        throw new Error(await readResponseError(contextResponse));
      }
      const [health, savedConversations, selectedWorkspace, savedContext] = await Promise.all([
        healthResponse.json() as Promise<{
          model: string;
          model_installed: boolean;
          message: string;
        }>,
        conversationsResponse.json() as Promise<Conversation[]>,
        workspaceResponse.json() as Promise<{ path: string }>,
        contextResponse.json() as Promise<{ context: string }>,
      ]);
      if (!active) return;
      setModelStatus(
        health.model_installed ? `Local · ${health.model}` : health.message,
      );
      setConversations(savedConversations);
      setWorkspace(selectedWorkspace.path);
      setWorkspaceInput(selectedWorkspace.path);
      setProjectContext(savedContext.context);
      setProjectContextDraft(savedContext.context);
      setProjectContextReady(true);
      void fetchAutonomy();
    };
    void initialize().catch((reason: unknown) => {
      if (!active) return;
      setError(errorText(reason, "Could not load Nexus AI."));
      setModelStatus("Backend unavailable");
    });
    return () => {
      active = false;
    };
  }, [fetchAutonomy]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading, progress]);

  async function createChat() {
    if (loading) return;
    setError("");
    try {
      const response = await fetch(`${apiUrl}/api/conversations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: "New chat" }),
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      const created = await response.json() as { id: number };
      setConversationId(created.id);
      setMessages([]);
      setProgress([]);
      setAgentTask(null);
      setRetryTurnId(null);
      setResearchSources([]);
      setAttachedFiles([]);
      await refreshConversations();
    } catch (reason) {
      setError(errorText(reason, "Could not create a chat."));
    }
  }

  async function selectChat(id: number) {
    if (loading) return;
    setError("");
    try {
      const response = await fetch(`${apiUrl}/api/conversations/${id}`);
      if (!response.ok) throw new Error(await readResponseError(response));
      const data = await response.json() as {
        conversation: { id: number };
        messages: Array<
          {
            id: number;
            role: "user" | "assistant" | "system";
            content: string;
            client_message_id: string | null;
          }
        >;
      };
      setConversationId(data.conversation.id);
      setMessages(
        data.messages
          .filter(
            (message): message is typeof message & { role: "user" | "assistant" } =>
              message.role === "user" || message.role === "assistant",
          )
          .map(({ id: messageId, role, content, client_message_id }) => ({
            id: messageId,
            role,
            content,
            turnId: client_message_id ?? undefined,
          })),
      );
      setRetryTurnId(null);
      setProgress([]);
    } catch (reason) {
      setError(errorText(reason, "Could not open that chat."));
    }
  }

  async function deleteChat(id: number) {
    if (loading || !window.confirm("Delete this chat and its messages permanently?")) return;
    setError("");
    try {
      const response = await fetch(`${apiUrl}/api/conversations/${id}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readResponseError(response));
      const remaining = conversations.filter((conversation) => conversation.id !== id);
      setConversations(remaining);
      if (conversationId === id) {
        if (remaining.length) await selectChat(remaining[0].id);
        else {
          setConversationId(null);
          setMessages([]);
          setProgress([]);
        }
      }
    } catch (reason) {
      setError(errorText(reason, "Could not delete that chat."));
    }
  }

  async function renameChat(id: number) {
    const current = conversations.find((c) => c.id === id);
    const newTitle = window.prompt("Rename chat:", current?.title || "New chat");
    if (!newTitle || !newTitle.trim() || newTitle === current?.title) return;
    try {
      const response = await fetch(`${apiUrl}/api/conversations/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      await refreshConversations();
    } catch (reason) {
      setError(errorText(reason, "Could not rename chat."));
    }
  }

  async function exportChat(id: number, format: "markdown" | "json") {
    try {
      const resp = await fetch(`${apiUrl}/api/conversations/${id}/export?format=${format}`);
      if (!resp.ok) throw new Error("Export failed");
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `nexus_chat_${id}.${format === "markdown" ? "md" : "json"}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Could not export conversation.");
    }
  }

  async function handleAttachFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
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
        if (!resp.ok) throw new Error(data.detail || "Upload failed");
        setAttachedFiles((prev) => [...prev, file.name]);
        setProgress((prev) => [
          ...prev,
          `Attached and indexed "${file.name}" (${data.chunk_count} chunks)`,
        ]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "File attachment failed");
      }
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  }

  async function setSelectedWorkspace() {
    if (loading) return;
    setError("");
    try {
      const response = await fetch(`${apiUrl}/api/workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: workspaceInput.trim() }),
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      const data = await response.json() as { path: string };
      setWorkspace(data.path);
      setWorkspaceInput(data.path);
      setProjectContextReady(false);
      setProjectContext("");
      setProjectContextDraft("");
      const contextResponse = await fetch(`${apiUrl}/api/workspace/context`);
      if (!contextResponse.ok) {
        throw new Error(await readResponseError(contextResponse));
      }
      const savedContext = await contextResponse.json() as { context: string };
      setProjectContext(savedContext.context);
      setProjectContextDraft(savedContext.context);
      setProjectContextReady(true);
      void fetchAutonomy();
      setProgress((current) => [...current, `Workspace selected: ${data.path}`]);
    } catch (reason) {
      setError(errorText(reason, "Could not select that workspace."));
    }
  }

  async function saveProjectContext() {
    if (!projectContextReady || loading || projectContextSaving) return;
    setError("");
    setProjectContextSaving(true);
    try {
      const response = await fetch(`${apiUrl}/api/workspace/context`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: projectContextDraft }),
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      const data = await response.json() as { context: string };
      setProjectContext(data.context);
      setProjectContextDraft(data.context);
      setProgress((current) => [...current, "Project context saved for this workspace."]);
    } catch (reason) {
      setError(errorText(reason, "Could not save project context."));
    } finally {
      setProjectContextSaving(false);
    }
  }

  async function clearProjectContext() {
    if (!projectContextReady || loading || projectContextSaving) return;
    if (!window.confirm("Clear the saved project context for this workspace?")) return;
    setError("");
    setProjectContextSaving(true);
    try {
      const response = await fetch(`${apiUrl}/api/workspace/context`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ context: "" }),
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      setProjectContext("");
      setProjectContextDraft("");
      setProgress((current) => [...current, "Saved project context cleared."]);
    } catch (reason) {
      setError(errorText(reason, "Could not clear project context."));
    } finally {
      setProjectContextSaving(false);
    }
  }

  async function decideApproval(approved: boolean) {
    if (!approval) return;
    setError("");
    try {
      const response = await fetch(
        `${apiUrl}/api/agent/approval/${approval.approvalId}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            approved,
            action_digest: approval.actionDigest,
          }),
        },
      );
      if (!response.ok) throw new Error(await readResponseError(response));
      setProgress((current) => [
        ...current,
        `${approved ? "Approved" : "Denied"}: ${approval.detail}`,
      ]);
      setApproval(null);
    } catch (reason) {
      setError(errorText(reason, "Could not submit approval."));
    }
  }

  async function sendMessage(retry = false) {
    if (loading) return;
    let content = input.trim();
    let turnId: string = crypto.randomUUID();
    let baseMessages = messages;

    if (retry) {
      const assistantIndex = messages.findLastIndex(
        (message) => message.role === "assistant" && message.turnId === retryTurnId,
      );
      if (assistantIndex < 0) return;
      const userIndex = assistantIndex - 1;
      if (userIndex < 0 || messages[userIndex].role !== "user") return;
      content = messages[userIndex].content;
      turnId = messages[userIndex].turnId ?? turnId;
      baseMessages = messages.slice(0, userIndex);
    } else if (!content) {
      return;
    } else if (retryTurnId && messages.at(-1)?.role === "assistant") {
      baseMessages = messages.slice(0, -1);
    }

    // Append attached file hints if any
    let fullContent = content;
    if (attachedFiles.length > 0 && !retry) {
      fullContent = `[Referenced Attachments: ${attachedFiles.join(", ")}]\n\n${content}`;
    }

    const userMessage: Message = { role: "user", content: fullContent, turnId };
    const nextMessages = retry
      ? [...baseMessages, userMessage, { role: "assistant" as const, content: "", turnId }]
      : [...messages, userMessage, { role: "assistant" as const, content: "", turnId }];
    const assistantIndex = nextMessages.length - 1;
    setMessages(nextMessages);
    setInput("");
    setError("");
    setRetryTurnId(turnId);
    setProgress([]);
    setAgentTask(null);
    setApproval(null);
    setLoading(true);

    const controller = new AbortController();
    activeRequest.current = controller;
    let receivedDone = false;
    let terminalError = false;

    const appendAssistant = (text: string, append: boolean) => {
      setMessages((current) =>
        current.map((message, index) =>
          index === assistantIndex
            ? { ...message, content: append ? message.content + text : text }
            : message,
        ),
      );
    };
    const addProgress = (text: string) =>
      setProgress((current) => [...current, text]);

    try {
      const payloadMessages = sanitizeMessagePayload([...baseMessages, userMessage]);
      if (!payloadMessages.length) {
        throw new Error("A non-empty message is required before sending.");
      }

      // Route by mode
      let endpoint = `${apiUrl}/api/chat`;
      let requestBody: Record<string, unknown> = {
        messages: payloadMessages,
        conversation_id: conversationId,
        turn_id: turnId,
      };

      if (mode === "agent") {
        endpoint = `${apiUrl}/api/agent`;
      } else if (mode === "research") {
        endpoint = `${apiUrl}/api/research`;
        requestBody = {
          query: fullContent,
          conversation_id: conversationId,
          turn_id: turnId,
          depth: researchDepth,
        };
      }

      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/x-ndjson",
        },
        body: JSON.stringify(requestBody),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(await readResponseError(response));
      if (!response.body) throw new Error("Streaming is not supported by this response.");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const processLine = (line: string) => {
        if (!line.trim()) return;
        const event = JSON.parse(line) as StreamEvent;
        if (event.conversation_id) setConversationId(event.conversation_id);
        if (event.type === "conversation_id" && event.conversation_id) {
          setConversationId(event.conversation_id);
        }
        if (event.token) appendAssistant(event.token, true);

        // Research events
        if (event.type === "research_plan" && event.step) {
          addProgress(`Research Plan (${event.step})`);
        }
        if (event.type === "research_step" && event.step) {
          addProgress(String(event.step));
        }
        if (event.type === "evidence_summary" && event.sources) {
          setResearchSources(event.sources);
          addProgress(`Gathered ${event.sources.length} evidence sources.`);
        }

        // Coding Agent events
        if (event.type === "plan" && event.steps) {
          addProgress(`Plan:\n${event.steps.map((step, index) => `${index + 1}. ${step}`).join("\n")}`);
        }
        if (event.type === "status" && event.message) addProgress(event.message);
        if (event.type === "task_progress" && event.message) {
          const label = event.status === "error" ? "Error" : event.status;
          addProgress(
            `${event.step ? `Step ${event.step}: ` : ""}${label ? `${label} — ` : ""}${event.message}`,
          );
        }
        if (event.type === "task_state" && event.task_id && event.state) {
          const taskId = event.task_id;
          const state = event.state;
          setAgentTask((current) => ({
            id: taskId,
            state,
            changedFiles: current?.id === taskId ? current.changedFiles : [],
            verificationStatus: current?.id === taskId
              ? current.verificationStatus
              : "not_required",
          }));
          if (event.message) addProgress(event.message);
        }
        if (event.type === "task_file_changed" && event.path) {
          const changedPath = event.path;
          setAgentTask((current) =>
            current
              ? {
                  ...current,
                  changedFiles: current.changedFiles.includes(changedPath)
                    ? current.changedFiles
                    : [...current.changedFiles, changedPath],
                  verificationStatus: "pending",
                }
              : current,
          );
        }
        if (event.type === "task_verification" && event.status) {
          setAgentTask((current) =>
            current ? { ...current, verificationStatus: event.status! } : current,
          );
        }
        if (event.type === "tool_start") addProgress(`Running tool: ${event.tool}`);
        if (event.type === "tool_result") {
          addProgress(`${event.tool} result:\n${safeText(event.output)}`);
        }
        if (event.type === "approval_required" && event.approval_id) {
          const request: Approval = {
            approvalId: event.approval_id,
            action: event.action ?? "operation",
            detail: event.detail ?? "Requested operation",
            diff: event.diff ?? "",
            actionDigest: event.action_digest ?? "",
            risk: event.risk ?? "RED",
            purpose: event.purpose ?? "Review the requested operation.",
            resource: event.resource ?? "Workspace operation",
            reversible: event.reversible ?? false,
            alternatives: event.alternatives ?? "Deny the request.",
          };
          setApproval(request);
          addProgress(`Approval required: ${request.detail}`);
        }
        if (event.type === "final" && event.content) appendAssistant(event.content, false);
        if (event.error) {
          setError(errorText(event.error, "The server reported an error."));
          terminalError = true;
          receivedDone = true;
        }
        if (event.done || event.type === "done") {
          receivedDone = true;
          setRetryTurnId(null);
          setApproval(null);
          void refreshConversations().catch((reason: unknown) => {
            setError(errorText(reason, "Could not refresh chat history."));
          });
        }
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        lines.forEach(processLine);
      }
      buffer += decoder.decode();
      if (buffer.trim()) processLine(buffer);
      if (!receivedDone && !controller.signal.aborted) {
        throw new Error("The response stream ended unexpectedly.");
      }
      if (!terminalError) await refreshConversations();
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) {
        setError(errorText(reason, "Unable to receive the response."));
      }
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
      setLoading(false);
      if (controller.signal.aborted) setApproval(null);
    }
  }

  function stopResponse() {
    if (mode === "agent" && agentTask?.id) {
      void fetch(`${apiUrl}/api/agent/tasks/${agentTask.id}/cancel`, {
        method: "POST",
      }).then(async (response) => {
        if (!response.ok) throw new Error(await readResponseError(response));
      }).catch((reason: unknown) => {
        setError(errorText(reason, "Could not cancel agent task."));
      });
    }
    if (activeRequest.current) {
      activeRequest.current.abort();
      activeRequest.current = null;
    }
    setLoading(false);
    setApproval(null);
  }

  const filteredConversations = conversations.filter((c) =>
    c.title.toLowerCase().includes(conversationSearch.toLowerCase()),
  );

  return (
    <div className="nexus-layout">
      {/* Top Application Navigation Bar */}
      <nav className="global-navbar">
        <div className="nav-brand" style={{ cursor: "pointer" }} onClick={() => setActiveTab("voice")}>
          <div className="brand-logo" style={{ background: "linear-gradient(135deg, #00f0ff, #7928ca)" }}>K</div>
          <span className="brand-title">KELA AI</span>
        </div>

        <div className="nav-tabs">
          <button
            className={`nav-tab ${activeTab === "voice" ? "active" : ""}`}
            onClick={() => setActiveTab("voice")}
            style={activeTab === "voice" ? { borderColor: "#00f0ff", color: "#00f0ff" } : {}}
          >
            🎙️ Voice & Jarvis
          </button>
          <button
            className={`nav-tab ${activeTab === "chat" ? "active" : ""}`}
            onClick={() => {
              if (conversationId) void selectChat(conversationId);
              setActiveTab("chat");
            }}
          >
            💬 Chat & Assistant
          </button>
          <button
            className={`nav-tab ${activeTab === "pc" ? "active" : ""}`}
            onClick={() => setActiveTab("pc")}
          >
            🖥️ PC Control
          </button>
          <button
            className={`nav-tab ${activeTab === "github" ? "active" : ""}`}
            onClick={() => setActiveTab("github")}
          >
            GitHub
          </button>
          <button
            className={`nav-tab ${activeTab === "imageStudio" ? "active" : ""}`}
            onClick={() => setActiveTab("imageStudio")}
          >
            Vision & Studio
          </button>
          <button
            className={`nav-tab ${activeTab === "browserAgent" ? "active" : ""}`}
            onClick={() => setActiveTab("browserAgent")}
          >
            Web Browser
          </button>
          <button
            className={`nav-tab ${activeTab === "knowledge" ? "active" : ""}`}
            onClick={() => setActiveTab("knowledge")}
          >
            Knowledge Engine
          </button>
          <button
            className={`nav-tab ${activeTab === "connectors" ? "active" : ""}`}
            onClick={() => setActiveTab("connectors")}
          >
            Data Connectors
          </button>
          <button
            className={`nav-tab ${activeTab === "memory" ? "active" : ""}`}
            onClick={() => setActiveTab("memory")}
          >
            Memory & Context
          </button>
          <button
            className={`nav-tab ${activeTab === "settings" ? "active" : ""}`}
            onClick={() => setActiveTab("settings")}
          >
            Diagnostics
          </button>
        </div>

        <div className="nav-right">
          <div className="autonomy-pill" title={`Autonomy Level ${autonomyLevel}`}>
            <span style={{ fontSize: "0.75rem", opacity: 0.8 }}>Autonomy:</span>
            <select
              value={autonomyLevel}
              onChange={(e) => void changeAutonomy(Number(e.target.value))}
              className="autonomy-select"
            >
              <option value={1}>L1: Advisory</option>
              <option value={2}>L2: Plan Only</option>
              <option value={3}>L3: Assisted (Default)</option>
              <option value={4}>L4: Supervised</option>
              <option value={5}>L5: Full Auto</option>
            </select>
          </div>
          <button className="theme-pill" onClick={toggleTheme} title="Toggle theme">
            {theme === "dark" ? "🌙 Dark" : "☀️ Light"}
          </button>
          <div className="model-pill" title={modelStatus}>
            <span className={`status-dot ${modelStatus.startsWith("Local") ? "" : "status-warning"}`} />
            {modelStatus}
          </div>
        </div>
      </nav>

      {/* Main Tab Content */}
      {activeTab === "voice" && (
        <VoiceAssistant
          apiUrl={apiUrl}
          conversationId={conversationId}
          onConversationIdChange={(id) => {
            setConversationId(id);
            void refreshConversations();
          }}
          onSwitchToTextChat={() => {
            if (conversationId) void selectChat(conversationId);
            setActiveTab("chat");
          }}
        />
      )}
      {activeTab === "pc" && <PCControlView apiUrl={apiUrl} />}
      {activeTab === "github" && <GitHubManager apiUrl={apiUrl} />}
      {activeTab === "imageStudio" && <ImageStudio apiUrl={apiUrl} />}
      {activeTab === "browserAgent" && <BrowserAgentView apiUrl={apiUrl} />}
      {activeTab === "knowledge" && <KnowledgeManager apiUrl={apiUrl} />}
      {activeTab === "connectors" && <DatabaseConnectors apiUrl={apiUrl} />}
      {activeTab === "memory" && <MemoryManager apiUrl={apiUrl} />}
      {activeTab === "settings" && (
        <SettingsView apiUrl={apiUrl} theme={theme} onToggleTheme={toggleTheme} />
      )}

      {activeTab === "chat" && (
        <main className="app-shell">
          <aside className="sidebar" aria-label="Chat history and workspace">
            <button className="new-chat" onClick={() => void createChat()} disabled={loading}>
              <span aria-hidden="true">+</span> New chat
            </button>

            <div className="chat-search-box">
              <input
                type="text"
                placeholder="Search chats..."
                value={conversationSearch}
                onChange={(e) => setConversationSearch(e.target.value)}
              />
            </div>

            <h2 className="history-heading">Recent chats</h2>
            <nav className="history-list" aria-label="Recent chats">
              {filteredConversations.map((conversation) => (
                <div
                  className={`history-item ${conversationId === conversation.id ? "active" : ""}`}
                  key={conversation.id}
                >
                  <button
                    className="history-select"
                    onClick={() => void selectChat(conversation.id)}
                    disabled={loading}
                    aria-current={conversationId === conversation.id ? "page" : undefined}
                    title={conversation.title}
                  >
                    {conversation.title}
                  </button>

                  <button
                    className="icon-action-btn"
                    onClick={() => void renameChat(conversation.id)}
                    disabled={loading}
                    title="Rename chat"
                  >
                    ✎
                  </button>
                  <button
                    className="icon-action-btn"
                    onClick={() => void exportChat(conversation.id, "markdown")}
                    disabled={loading}
                    title="Export Markdown"
                  >
                    ⬇
                  </button>
                  <button
                    className="delete-chat"
                    onClick={() => void deleteChat(conversation.id)}
                    disabled={loading}
                    aria-label={`Delete ${conversation.title}`}
                    title="Delete chat"
                  >
                    ✕
                  </button>
                </div>
              ))}
              {!filteredConversations.length && (
                <p className="empty-history">
                  {conversationSearch ? "No matching chats found." : "Your saved chats will appear here."}
                </p>
              )}
            </nav>

            <div className="workspace-card">
              <label htmlFor="workspace-path">Selected workspace</label>
              <input
                id="workspace-path"
                value={workspaceInput}
                onChange={(event) => setWorkspaceInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void setSelectedWorkspace();
                }}
                disabled={loading}
                aria-describedby="workspace-permission"
              />
              <button onClick={() => void setSelectedWorkspace()} disabled={loading || !workspaceInput.trim()}>
                Select folder path
              </button>
              <p id="workspace-permission">Read-only inspection by default. Writes and commands need your approval.</p>
              <span className="workspace-current" title={workspace}>{workspace || "Loading workspace..."}</span>

              <label htmlFor="project-context">Saved project context</label>
              <textarea
                id="project-context"
                value={projectContextDraft}
                onChange={(event) => setProjectContextDraft(event.target.value)}
                maxLength={8000}
                rows={3}
                placeholder="Project conventions, architecture notes, or preferences..."
                disabled={loading || projectContextSaving || !projectContextReady}
                aria-describedby="project-context-help"
              />
              <p id="project-context-help">
                Saved locally per workspace and included in chat and agent prompts.
                {" "}{projectContextDraft.length}/8000
              </p>
              <div className="workspace-context-actions">
                <button
                  onClick={() => void saveProjectContext()}
                  disabled={
                    loading ||
                    projectContextSaving ||
                    !projectContextReady ||
                    projectContextDraft === projectContext
                  }
                >
                  {projectContextSaving ? "Saving..." : "Save context"}
                </button>
                <button
                  className="workspace-context-clear"
                  onClick={() => void clearProjectContext()}
                  disabled={
                    loading ||
                    projectContextSaving ||
                    !projectContextReady ||
                    (!projectContext && !projectContextDraft)
                  }
                >
                  Clear
                </button>
              </div>
            </div>

            <div className="privacy-card">
              <span className="status-dot" />
              <div>
                <strong>Local mode</strong>
                <p>Private Ollama inference on your laptop.</p>
              </div>
            </div>
          </aside>

          <StudentTasksPanel apiUrl={apiUrl} />

          <section className="chat-panel">
            <header className="topbar">
              <div>
                <span className="eyebrow">ASSISTANT WORKSPACE</span>
                <h2>
                  {mode === "chat" && "Conversational Assistant"}
                  {mode === "research" && "Deep Research & Reasoning Agent"}
                  {mode === "agent" && "Autonomous Coding Agent"}
                </h2>
              </div>
              <div className="topbar-controls">
                <label className="mode-toggle">
                  <span>Mode</span>
                  <select
                    value={mode}
                    onChange={(event) => setMode(event.target.value as AssistantMode)}
                    disabled={loading}
                    aria-label="Assistant mode"
                  >
                    <option value="chat">Local Chat</option>
                    <option value="research">Deep Research Agent</option>
                    <option value="agent">Coding Agent</option>
                  </select>
                </label>

                {mode === "research" && (
                  <label className="depth-toggle">
                    <span>Depth</span>
                    <select
                      value={researchDepth}
                      onChange={(e) => setResearchDepth(e.target.value as ResearchDepth)}
                      disabled={loading}
                    >
                      <option value="quick">Quick (Top 3)</option>
                      <option value="standard">Standard (Top 5)</option>
                      <option value="deep">Deep (Top 8)</option>
                    </select>
                  </label>
                )}
              </div>
            </header>

            <section className="conversation" aria-live="polite">
              {messages.length === 0 ? (
                <div className="welcome">
                  <div className="welcome-logo" style={{ background: "linear-gradient(135deg, #00f0ff, #7928ca)" }}>K</div>
                  <span className="eyebrow">INTEGRATED PERSONAL AI OPERATING SYSTEM</span>
                  <h2>How can KELA help you today?</h2>
                  <p>
                    Voice-first personal operating system with real PC control, deep grounded research, autonomous coding, and memory.
                  </p>
                  <div className="suggestions">
                    {[
                      "What is my current battery and CPU status?",
                      "Take a desktop screenshot and analyze it",
                      "Open VS Code and check Git branch status",
                    ].map((suggestion) => (
                      <button
                        key={suggestion}
                        disabled={loading}
                        onClick={() => setInput(suggestion)}
                      >
                        {suggestion} <span>→</span>
                      </button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="message-list">
                  {messages.map((message, index) => (
                    <article
                      className={`message ${message.role}`}
                      key={message.id ?? message.turnId ?? index}
                    >
                      <div className="avatar" aria-hidden="true">
                        {message.role === "user" ? "U" : "K"}
                      </div>
                      <div className="message-body">
                        <div className="message-header-row">
                          <strong className="message-label">
                            {message.role === "user" ? "You" : "KELA"}
                          </strong>
                          {message.role === "assistant" && !loading && index === messages.length - 1 && (
                            <button
                              className="btn-retry-icon"
                              onClick={() => void sendMessage(true)}
                              title="Regenerate response"
                            >
                              ↻ Regenerate
                            </button>
                          )}
                        </div>
                        <div className="message-text">
                          {message.content ? (
                            <Markdown content={message.content} />
                          ) : (
                            loading && message.role === "assistant" && (
                              <p className="thinking">Thinking locally...</p>
                            )
                          )}
                        </div>
                      </div>
                    </article>
                  ))}
                  <div ref={bottomRef} />
                </div>
              )}

              {/* Research Evidence Sources Carousel */}
              {researchSources.length > 0 && (
                <div className="research-sources-box">
                  <h4>Grounded Evidence Sources ({researchSources.length})</h4>
                  <div className="evidence-grid">
                    {researchSources.map((s) => (
                      <div className="evidence-item" key={s.citation_id}>
                        <div className="evidence-head">
                          <span className="citation-badge">{s.citation_id}</span>
                          <strong>{s.title}</strong>
                        </div>
                        <p className="evidence-snippet">{s.snippet}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {progress.length > 0 && (
                <details className="agent-progress" open={loading}>
                  {agentTask && (
                    <p className="agent-task-state">
                      Task {agentTask.id} · {agentTask.state} · verification: {agentTask.verificationStatus}
                      {agentTask.changedFiles.length > 0 && (
                        <> · changed: {agentTask.changedFiles.join(", ")}</>
                      )}
                    </p>
                  )}
                  <summary>Activity Timeline ({progress.length})</summary>
                  <ol>
                    {progress.map((item, index) => <li key={`${index}-${item.slice(0, 30)}`}>{item}</li>)}
                  </ol>
                </details>
              )}

              {approval && (
                <section className="approval-card" aria-label="Approval required">
                  <h3>Approval required · {approval.risk}</h3>
                  <dl className="approval-details">
                    <dt>Purpose</dt><dd>{approval.purpose}</dd>
                    <dt>Affected resource</dt><dd>{approval.resource}</dd>
                    <dt>Reversibility</dt>
                    <dd>{approval.reversible ? "Reversible" : "Potentially irreversible"}</dd>
                    <dt>Safer alternative</dt><dd>{approval.alternatives}</dd>
                  </dl>
                  <p>{approval.detail}</p>
                  {approval.diff && (
                    <pre className="approval-diff"><code>{approval.diff}</code></pre>
                  )}
                  <div className="approval-actions">
                    <button
                      onClick={() => void decideApproval(true)}
                      disabled={!approval.actionDigest}
                    >
                      Approve once
                    </button>
                    <button
                      onClick={() => void decideApproval(false)}
                      disabled={!approval.actionDigest}
                    >
                      Deny
                    </button>
                    <button onClick={stopResponse}>Cancel task</button>
                  </div>
                </section>
              )}

              {error && (
                <div className="error-banner" role="alert">
                  <span>{error}</span>
                  {retryTurnId && !loading && (
                    <button onClick={() => void sendMessage(true)}>Retry</button>
                  )}
                </div>
              )}
            </section>

            <footer className="composer-area">
              {attachedFiles.length > 0 && (
                <div className="attachments-bar">
                  <span>Attachments:</span>
                  {attachedFiles.map((fn, i) => (
                    <span className="attachment-chip" key={i}>
                      📄 {fn}
                      <button
                        onClick={() => setAttachedFiles((prev) => prev.filter((_, idx) => idx !== i))}
                      >
                        ✕
                      </button>
                    </span>
                  ))}
                </div>
              )}

              <div className="composer">
                <input
                  type="file"
                  ref={fileInputRef}
                  style={{ display: "none" }}
                  onChange={(e) => void handleAttachFile(e)}
                />
                <button
                  type="button"
                  className="attach-btn"
                  onClick={() => fileInputRef.current?.click()}
                  title="Attach & Index document"
                  disabled={loading}
                >
                  📎
                </button>

                <textarea
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendMessage();
                    }
                  }}
                  placeholder={
                    mode === "agent"
                      ? "Describe a coding task in the workspace..."
                      : mode === "research"
                        ? "Ask a research question grounded in knowledge and data..."
                        : "Message KELA..."
                  }
                  rows={2}
                  disabled={loading}
                  aria-label="Message"
                />
                {loading ? (
                  <button className="stop-button" onClick={stopResponse} aria-label="Stop response">
                    Stop
                  </button>
                ) : (
                  <button
                    className="send-button"
                    onClick={() => void sendMessage()}
                    disabled={!input.trim()}
                    aria-label="Send message"
                  >
                    ➤
                  </button>
                )}
              </div>
              <p className="composer-hint">
                Enter to send · Shift + Enter for new line · {mode === "agent" ? "Coding Agent requires approval" : mode === "research" ? "Deep Evidence Grounding" : "Local Ollama"}
              </p>
            </footer>
          </section>
        </main>
      )}
    </div>
  );
}
