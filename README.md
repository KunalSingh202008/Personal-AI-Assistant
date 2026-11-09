# NEXUS AI — AUTONOMOUS PERSONAL AI OPERATING SYSTEM

Nexus AI is an integrated, local-first personal AI operating system combining a conversational assistant, deep research agent, coding agent, multi-source knowledge engine, database connectors, and isolated personal memory.

---

## Architecture Overview

```
                      ┌────────────────────────────────────────┐
                      │    Nexus AI React + Vite Frontend      │
                      │  (Chat, Research, Coding, Knowledge,   │
                      │     Connectors, Memory, Settings)      │
                      └──────────────────┬─────────────────────┘
                                         │ HTTP / Streaming NDJSON
                                         ▼
                      ┌────────────────────────────────────────┐
                      │        FastAPI Backend (Port 8000)     │
                      └───────┬───────────────┬──────────────┬─┘
                              │               │              │
        ┌─────────────────────┼───────────────┤              │
        ▼                     ▼               ▼              ▼
┌──────────────┐     ┌────────────────┐ ┌──────────┐ ┌───────────────┐
│ Knowledge    │     │ Database       │ │ Memory   │ │ Coding Agent  │
│ Engine       │     │ Connectors     │ │ Layers   │ │ & Approval    │
│ - FTS5 + Vec │     │ - SQLite (ro)  │ │ 1. Chat  │ │ - Safe Tools  │
│ - Chunking   │     │ - CSV Datasets │ │ 2. Prefs │ │ - Diffs       │
│ - RRF Hybrid │     │ - Ext Adapters │ │ 3. Ctxt  │ │ - 60s timeout │
│ - MD/PDF/CSV │     │ - Redaction    │ │ 4. Doc   │ │ - Verification│
└───────┬──────┘     └────────┬───────┘ └────┬─────┘ └───────┬───────┘
        │                     │              │               │
        └─────────────────────┼──────────────┴───────────────┘
                              │
                              ▼
        ┌────────────────────────────────────────┐
        │        Local SQLite (nexus_ai.db)      │
        │        Local Ollama (qwen2.5-coder:7b) │
        └────────────────────────────────────────┘
```

### Core Capabilities

1. **Conversational Assistant**:
   - ChatGPT-like streaming responses.
   - Persistent chat history in SQLite with turn IDs and idempotency.
   - Conversation search, inline renaming, Markdown and JSON export.
   - Code syntax highlighting with copy buttons, retry, and regeneration.
   - File attachment support: pick files from disk to index and ground conversations.
   - Light and dark themes with persistent storage.

2. **Deep Research & Reasoning Agent**:
   - Multi-source evidence gathering across indexed files, databases, and authorized web search.
   - Grounded facts with bracketed numeric citations (`[1]`, `[2]`).
   - Confidence breakdown: Executive Summary, Verified Findings, Inferences & Working Estimates, and Knowledge Gaps.
   - Configurable research depth (`quick`, `standard`, `deep`).

3. **Multi-Source Knowledge Engine**:
   - Ingestion parsers for Markdown, TXT, Python, TypeScript, JSON, YAML, CSV, and PDF.
   - Recursive chunking with paragraph/code block boundary detection and configurable overlap.
   - Fast deterministic subword n-gram vector embeddings and cosine similarity.
   - SQLite FTS5 full-text indexing combined with vector semantic search using Reciprocal Rank Fusion (RRF).
   - Incremental indexing via SHA-256 content hashing to avoid redundant re-indexing.
   - Interactive document catalog, chunk inspector, and retrieval tester.

4. **Database & Structured Data Connectors**:
   - Isolated connector framework for SQLite, CSV datasets, and external database adapters.
   - Strict read-only enforcement: AST and regex parser blocks mutation statements (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`).
   - Automatic redaction of sensitive credentials and tokens in query results.
   - Interactive schema inspection (tables, columns, data types, row counts) and query console.

5. **Personal Memory & Context Isolation**:
   - Strict firewalls between 5 distinct memory layers:
     1. Conversation History (transient/saved chat turns).
     2. Persistent Preferences (user profile, communication tone, coding style).
     3. Workspace Project Context (scoped to selected workspace root, up to 8,000 characters).
     4. Retrieved Knowledge (on-demand chunks and citations).
     5. Ephemeral Task State (active coding plan, execution timeline, tool results).
   - Complete memory export snapshot and safe memory wipe controls.

6. **Controlled Coding Agent**:
   - Action Policy risk classification: **GREEN** (safe read-only inspection), **AMBER** (explicit user approval required for file writes, allowlisted commands, and Git commits), **RED** (unauthorized/destructive operations blocked).
   - Diff generation and approval gateway with cryptographic action digests and 120-second TTL.
   - Strict verification gates: tasks cannot be marked complete without passing allowlisted test commands.
   - Bounded retries and audit logging.

8. **KELA — Voice-First Autonomous Assistant**:
   - Continuous two-way conversational voice loop with zero-latency `isFinal` submission and 650 ms VAD fallback.
   - Dual Mode Architecture: Mode A (Continuous Voice with Web Speech TTS) and Mode B (Text Chat with streaming markdown).
   - Real-time barge-in and audio cancellation upon speech detection.
   - Sub-millisecond direct command routing for native Win32 controls without slow LLM roundtrips.
   - Bilingual support: automatic detection and routing for English, Hindi, and Hinglish.

9. **Native Windows PC Control**:
   - Ultra-low latency system control via Win32 `ctypes`:
     - Volume adjust & mute via `user32.keybd_event` (3.8 ms).
     - Battery & RAM metrics via `kernel32.GetSystemPowerStatus` and `GlobalMemoryStatusEx` (5.2 ms).
   - Application launcher for Chrome, VS Code, Calculator, and Windows Camera UWP protocol.
   - Real filesystem intelligence: recent file resolution by `mtime`, resume locator, and default OS handler invocation.
   - Live internet research: DuckDuckGo live search with spoken LLM summarization.

---

## Start and Stop on Windows

### 1. Launch the System
From the repository root in PowerShell:

```powershell
.\Start-Nexus.ps1
```

The launcher:
- Validates Python (3.14+), Node/npm, and the virtual environment.
- Checks local Ollama connectivity and verifies `qwen2.5-coder:7b`.
- Starts the FastAPI backend (port 8000) and Vite frontend (port 5173/5174).
- Isolates processes from terminal Ctrl+C and logs output under `%LOCALAPPDATA%\NexusAI\logs`.

### 2. Stop the System
```powershell
.\Start-Nexus.ps1 -Stop
```

---

## Verification & Testing

### Run All Unit Tests
From the repository root:

```powershell
Push-Location backend
try { .\.venv\Scripts\python.exe -m unittest discover -s tests -v } finally { Pop-Location }
```

### Run Frontend Lint & Production Build
```powershell
Push-Location frontend
try {
  npm run lint
  npm run build
} finally { Pop-Location }
```

### Run System Smoke Test Suite
```powershell
.\backend\.venv\Scripts\python.exe nexus_smoke_test.py -v
```

---

## REST API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/health` | GET | Check Ollama and model readiness |
| `/api/models` | GET | List installed Ollama models |
| `/api/models/select` | POST | Select active inference model tag |
| `/api/chat` | POST | Streaming conversational chat |
| `/api/research` | POST | Streaming deep research agent |
| `/api/agent` | POST | Streaming coding agent loop |
| `/api/conversations` | GET, POST | List or create conversations |
| `/api/conversations/{id}` | GET, PATCH, DELETE | Fetch, rename, or delete conversation |
| `/api/conversations/{id}/export` | GET | Export conversation as Markdown or JSON |
| `/api/knowledge/documents` | GET | List indexed documents |
| `/api/knowledge/documents/{id}` | GET, DELETE | Inspect document chunks or delete from index |
| `/api/knowledge/index-file` | POST | Index file by local path |
| `/api/knowledge/index-directory` | POST | Scan and index directory |
| `/api/knowledge/upload` | POST | Upload and index file |
| `/api/knowledge/search` | POST | Test hybrid FTS5 + semantic search |
| `/api/connectors` | GET, POST | List or register database connectors |
| `/api/connectors/{id}/test` | GET | Test connector connectivity and latency |
| `/api/connectors/{id}/schema` | GET | Inspect tables, columns, and row counts |
| `/api/connectors/{id}/query` | POST | Execute safe read-only SQL/CSV query |
| `/api/memory/preferences` | GET, PUT | Get or save user preferences |
| `/api/memory/preferences/{key}` | DELETE | Remove user preference |
| `/api/memory/export` | GET | Export memory snapshot JSON |
| `/api/memory/clear` | POST | Wipe preferences and workspace context |
| `/api/agent/tools` | GET | Tool JSON schemas |
| `/api/agent/activity` | GET | Security audit log |
| `/api/agent/approval/{id}` | POST | Decide approval request (Approve/Deny) |
| `/api/agent/servers` | GET | List active workspace Python servers |
| `/api/voice/conversation` | POST | Continuous voice assistant loop with spoken responses |
| `/api/voice/command` | POST | Direct voice action dispatcher |
| `/api/pc/launch` | POST | Launch Windows apps (calc, camera, chrome, code) |
| `/api/pc/close` | POST | Terminate Windows process by name |
| `/api/pc/volume` | POST | Adjust system volume via native Win32 API |
| `/api/pc/mute` | POST | Toggle system mute via Win32 keybd_event |
| `/api/pc/metrics` | GET | Native CPU, RAM, and Battery power status |
| `/api/pc/screenshot` | POST | Capture high-resolution desktop screenshot |
| `/api/pc/files/search` | POST | Search user files by name or extension |
| `/api/pc/files/recent` | POST | Locate and launch most recent file by mtime |
| `/api/pc/files/resume` | POST | Locate resume documents in Downloads/Documents |
