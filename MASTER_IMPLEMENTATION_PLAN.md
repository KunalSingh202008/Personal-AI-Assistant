# MASTER IMPLEMENTATION PLAN — KELA AI PLATFORM
## Execution Blueprint: Transforming KELA into an Intelligent Personal AI Operating Assistant
**Repository**: `https://github.com/KunalSingh202008/Personal-AI-Assistant.git`  
**Baseline**: Branch `main`, Commit `2c24e80`  
**Date**: November 12, 2026  
**Status**: Ready for User Review and Acceptance  

---

## 1. High-Level Architectural Vision

KELA must operate as a unified, conversational Personal Operating Assistant across both Voice and Text interfaces. The existing foundation (KelaEngine, SQLite persistence, ProviderManager, Knowledge Engine RAG, and native Win32 ctypes) will be preserved and extended into a modular, tool-empowered system.

```
User Utterance (Voice or Text)
           │
           ▼
┌────────────────────────────────────────────────────────┐
│             KelaEngine.process_turn()                  │
│  - Session lookup & atomic turn lock                   │
│  - Load conversation history & active entity context   │
└──────────────────────────┬─────────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────┐
│     Natural Language Intent & Task Engine (Phase C)    │
│  - Detects language (English, Hindi, Hinglish)         │
│  - Distinguishes Informational Query vs Action Request │
│  - Extracts Entities (Project, File, App, Drive, Path) │
│  - Resolves Pronouns ("it", "that project") from Memory│
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
      [Informational Query]      [Actionable Task Plan]
               │                          │
               ▼                          ▼
┌──────────────────────────┐    ┌──────────────────────────────────┐
│ KelaEngine + RAG (Opt.)  │    │ Autonomous Task Planner (Phase H)│
│  - Knowledge base ground │    │  - Decomposes multi-step tasks   │
│  - Direct LLM response   │    │  - Checks tool risk policy       │
└──────────────┬───────────┘    └─────────────────┬────────────────┘
               │                                  │
               │               ┌──────────────────┴──────────────────┐
               │               │                                     │
               │         [GREEN: Safe]                        [AMBER: Risky]
               │               │                                     │
               │               ▼                                     ▼
               │    ┌──────────────────────┐             ┌──────────────────────┐
               │    │ Direct Execution     │             │ Approval Ticket Req. │
               │    │ via ToolRegistry     │             │ (Voice or UI Confirm)│
               │    └──────────┬───────────┘             └──────────┬───────────┘
               │               │                                    │
               └───────────────┼────────────────────────────────────┘
                               ▼
┌────────────────────────────────────────────────────────┐
│            Verification & Response Generator           │
│  - Validates actual execution result (PID, file, HTTP) │
│  - Generates conversational spoken explanation (TTS)   │
│  - Updates Session Entity Memory for follow-ups        │
│  - Emits streaming UI event stream                     │
└────────────────────────────────────────────────────────┘
```

---

## 2. Controlled Implementation Phases

### PHASE B — Repair Voice Reliability & Natural-Language Interaction
**Objective**: Eliminate the regex wall and enable robust, natural conversational voice interactions across English, Hindi, and Hinglish.

#### Key Deliverables:
1. **Remove Brittle Regex Intent Wall (`backend/voice/router.py`)**:
   - Replace the 20+ hardcoded `re.search()` conditions with a fast hybrid intent router:
     - **Fast Path (0ms)**: Preserves immediate system commands (*stop listening*, *pause*, *mute*, *volume up/down*).
     - **Intelligent Path**: Routes natural language utterances to the central Intent & Task Engine.
2. **Language Awareness (English, Hindi, Hinglish)**:
   - Expand `detect_language()` to recognize bilingual Hindi/English phrases (*"mera Phone Doctor project chalao"*, *"resume kahan hai"*, *"system check karo"*).
   - Ensure the assistant responds naturally in the user's chosen language without breaking tool execution.
3. **Conversational Feedback & No-Silent-Failure Policy**:
   - Every utterance produces spoken confirmation, clarification question, or explanation.
   - If a command cannot be understood with high confidence, KELA asks: *"Did you want me to search for a file or run an application?"* instead of remaining silent.
4. **Interruption & Listening Recovery**:
   - Validate continuous listening state machine in `VoiceAssistant.tsx`.
   - Prevent microphone feedback loops with Web Audio Analyser echo suppression.
   - Ensure instant barge-in cancels speech synthesis immediately and resets the listening pipeline.

---

### PHASE C — Shared Intent Engine, Context Resolution & Unified Tool Registry
**Objective**: Build a modular, LLM-driven intent classification and tool orchestration layer shared between voice and text chat.

#### Key Deliverables:
1. **Natural Language Intent Engine (`backend/core/intent_engine.py`)**:
   - Uses local model (`qwen2.5-coder:7b`) with a structured schema to output:
     ```json
     {
       "intent_type": "ACTION" | "QUESTION" | "CLARIFICATION_NEEDED",
       "action_category": "PC_CONTROL" | "FILE_SEARCH" | "PROJECT_RUNNER" | "STORAGE_AUDIT" | "RAG" | "GENERAL",
       "tool_name": "find_project" | "run_project" | "analyze_storage" | "launch_app" | null,
       "parameters": { ... },
       "entities": { "project_name": "Phone Doctor", "file_type": "pdf" },
       "confidence": 0.95
     }
     ```
2. **Context & Entity Resolution (`backend/core/entity_tracker.py`)**:
   - Tracks active session entities: `last_mentioned_project`, `last_mentioned_file`, `last_mentioned_path`, `last_opened_app`.
   - Resolves pronouns (*"it"*, *"that project"*, *"the error"*) to the active entity in conversation history.
3. **Unified Tool Registry Expansion (`backend/core/tool_registry.py`)**:
   - Register all PC, Project, Storage, and File tools with full JSON schemas and typed parameters.
   - Decouple tool invocation from FastAPI routes so both `chat_stream` and `process_voice_turn` can invoke tools directly.

---

### PHASE D — Personal File and Project Discovery
**Objective**: Enable natural-language discovery of files and development projects across all permitted Windows drives.

#### Key Deliverables:
1. **Project Manifest Detector (`backend/pc_control/project_detector.py`)**:
   - Recognizes project roots by detecting manifests:
     - React / Node / Next.js: `package.json`
     - Python: `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py`
     - Android / Java: `build.gradle`, `pom.xml`, `settings.gradle`
     - Rust / Go / C++: `Cargo.toml`, `go.mod`, `CMakeLists.txt`
     - Version control: `.git` directory
2. **Bounded Background Indexer & Cache (`backend/pc_control/file_indexer.py`)**:
   - Scans user drives (`C:\Users\Kunal Singh\Documents`, `Downloads`, `Desktop`, `Projects`, custom drive roots) in the background.
   - Caches project locations and file metadata in SQLite (`indexed_projects`, `file_catalog` tables).
   - Incremental scanning: only updates when directory modified timestamp changes.
   - Zero entire-drive freezing.
3. **Natural Language File Search Tool (`find_files_or_projects`)**:
   - Supports natural language filters: by name, extension (`.pdf`, `.md`, `.tsx`), date range (*"modified this week"*), and minimum/maximum size (*"biggest files"*).
   - Returns absolute paths, project tech stack, size, and modified date.
   - Provides options to open the file or open the containing folder in Windows Explorer.

---

### PHASE E — Intelligent Storage and Memory Manager
**Objective**: Provide comprehensive RAM, disk storage, and safe cleanup intelligence without mocked data.

#### Key Deliverables:
1. **Genuine Windows Process & RAM Enumeration (`backend/pc_control/system_ops.py`)**:
   - Replace the hardcoded mock array with native Windows API calls (`EnumProcesses` + `GetProcessMemoryInfo` or `psutil` if available, falling back to native `tasklist /FO CSV`).
   - Reports: Total RAM, Free RAM, Used RAM, Top 10 memory-consuming active processes with genuine working set sizes.
2. **Drive & Storage Analyzer (`backend/pc_control/storage_analyzer.py`)**:
   - Inspects all mounted drives (`GetDiskFreeSpaceExW` via ctypes): total capacity, used space, free space.
   - Identifies largest user directories and project folders.
3. **Project-Aware Cleanup Recommendation Engine**:
   - Analyzes safe cleanup targets:
     - Temporary files (`%TEMP%`, `C:\Windows\Temp`).
     - Build artifacts & caches (`node_modules` in inactive projects, `.venv` copies, `__pycache__`, `.pytest_cache`, `dist`, `build`, `.gradle/caches`).
     - Duplicate files identified via partial SHA-256 chunk hashing.
     - Old Downloads files older than 30 days.
   - Classifies every recommendation:
     - `SAFE_CLEANUP`: Browser caches, temp files, stale `__pycache__`.
     - `REVIEW_BEFORE_REMOVAL`: Inactive `node_modules`, old downloads.
     - `KEEP`: User source code, project assets, personal files.
4. **Reversible Quarantine & Approval Enforcement**:
   - **Zero Silent Deletions**: Deletion requires explicit user approval.
   - Moves files to Windows Recycle Bin (`SHFileOperationW` with `FO_DELETE` + `FOF_ALLOWUNDO`) or local `.kela_quarantine/` instead of permanent deletion.

---

### PHASE F — Intelligent Project Runner & Process Management
**Objective**: Automatically discover, configure, launch, monitor, and stop supported development projects on localhost.

#### Key Deliverables:
1. **Modular Project Adapters (`backend/pc_control/runners/`)**:
   - `BaseProjectRunner`: Interface with `detect()`, `prepare()`, `start()`, `health_check()`, `stop()`.
   - `ViteReactRunner`: Inspects `package.json` scripts, detects package manager (`npm`, `yarn`, `pnpm`), launches dev server.
   - `NextJsRunner`: Detects `next dev`, inspects port.
   - `NodeExpressRunner`: Detects entry file (`server.js`, `index.js`, `app.js`).
   - `FastApiRunner`: Detects `uvicorn main:app`, virtualenv Python interpreter.
   - `FlaskRunner`: Detects `flask run` or `python app.py`.
   - `GradleAndroidRunner`: Explains that it is an Android mobile project, checks Android SDK, and provides emulator/build instructions instead of misfiring a localhost server.
2. **Port Conflict Detection & Environmental Safety**:
   - Probes target port (`netstat` / `socket.bind`) prior to startup.
   - If port 3000 or 8000 is occupied, automatically selects the next available port or reports the conflicting process name.
3. **Process Supervision & Verification**:
   - Spawns subprocess in detached process group, tracks PID in `managed_processes` table.
   - Captures stdout/stderr in memory buffer for error diagnosis.
   - Actively polls the HTTP endpoint (e.g. `http://localhost:5173`) until it returns HTTP 200/300 before declaring the project successfully running.
   - Returns verified clickable localhost URL.
4. **Safe Process Termination**:
   - Allows KELA to terminate **only** the PIDs it started. Refuses to terminate system processes or unrelated user applications.

---

### PHASE G — General Windows PC Operator
**Objective**: Provide native Windows desktop operator capabilities through safe registered tools.

#### Key Deliverables:
1. **Application Management**:
   - Launch verified applications (`app_launcher.py`) with process running verification (`is_process_running`).
   - Close managed applications safely with graceful window close (`WM_CLOSE`) before force termination.
2. **Audio & System Controls**:
   - Fine-grained master volume adjustments (step up/down, mute toggle, explicit percentage).
   - Battery and power status reporting.
3. **Browser & Research Actions**:
   - Open specific validated URLs in user's default browser.
   - Real-time web search with conversational spoken summary via `BrowserAgent` or search API.
4. **Desktop Capture**:
   - High-resolution screen capture saved to designated local directory for multimodal inspection.

---

### PHASE H — Memory, Task Planning & RAG Integration
**Objective**: Connect autonomous multi-step task planning with persistent memory and Phase 3 knowledge bases.

#### Key Deliverables:
1. **Autonomous Task Planner (`backend/core/task_planner.py`)**:
   - Decomposes composite requests (e.g. *"Find Phone Doctor and run it locally"*) into explicit ordered milestones:
     - Step 1: `find_project("Phone Doctor")` $\rightarrow$ resolves `C:\Projects\PhoneDoctor`
     - Step 2: `inspect_project_manifest()` $\rightarrow$ detects React/Vite
     - Step 3: `check_port_availability(5173)` $\rightarrow$ port is free
     - Step 4: `start_project_runner()` $\rightarrow$ spawns dev server
     - Step 5: `verify_http_readiness("http://localhost:5173")` $\rightarrow$ verified
     - Step 6: Formulate spoken and text outcome.
2. **Task State & Recovery**:
   - Emits step-by-step progress events to both voice status text and frontend chat progress UI.
   - If a step fails, diagnoses the error from captured logs and offers clear repair suggestions.
3. **Phase 3 RAG Preservation**:
   - Knowledge base grounding remains available via `kb_id`.
   - Strict KB isolation, genuine page/sheet citations, and prompt injection barriers are maintained.

---

### PHASE I — Security, End-to-End Tests & Windows Verification
**Objective**: Enforce approval boundaries, complete the Master Test Matrix, and verify real Windows execution.

#### Key Deliverables:
1. **Approval Gateway Integration**:
   - Safe operations (file search, memory check, safe app launch) execute automatically (`GREEN`).
   - Risky operations (file deletion, dependency installation, build commands, file overwrite) require explicit cryptographic approval tickets (`AMBER`).
   - The user can approve via UI button or clear spoken confirmation (*"Confirm execution"*).
2. **Secret Redaction**:
   - Logs and responses automatically redact API keys, passwords, and `.env` credentials using regex patterns.
3. **Execution of Master Test Matrix**:
   - All 119 existing unit tests pass without regression.
   - New unit tests for Intent Engine, File Indexer, Storage Analyzer, Project Runner, and Task Planner.
   - Live Windows acceptance verification.

---

## 3. Detailed File Modification Roadmap

| File / Module | Purpose in Master Plan |
|---|---|
| `backend/core/intent_engine.py` | **NEW**: Natural language intent & parameter extractor (English/Hindi/Hinglish). |
| `backend/core/entity_tracker.py` | **NEW**: Conversational entity & pronoun tracker (*"it"*, *"that project"*). |
| `backend/core/task_planner.py` | **NEW**: Multi-step plan generator & execution coordinator. |
| `backend/core/tool_registry.py` | **EXPAND**: Unified registry of all PC, Project, Storage, File, and RAG tools. |
| `backend/core/engine.py` | **UPDATE**: Route voice & chat through `intent_engine` $\rightarrow$ `task_planner` $\rightarrow$ `tool_registry`. |
| `backend/voice/router.py` | **REFACTOR**: Replace hardcoded regex wall with fast hybrid router connecting to intent engine. |
| `backend/pc_control/file_indexer.py` | **NEW**: Bounded filesystem indexer & Git project manifest detector. |
| `backend/pc_control/storage_analyzer.py`| **NEW**: RAM, drive usage, duplicate hash finder, and categorized cleanup analyzer. |
| `backend/pc_control/runners/` | **NEW**: Tech stack adapters (Vite, Next, Node, FastAPI, Flask, Gradle). |
| `backend/pc_control/system_ops.py` | **FIX**: Replace hardcoded process mocks with genuine Windows tasklist/Win32 APIs. |
| `frontend/src/components/VoiceAssistant.tsx` | **ENHANCE**: Support multi-turn conversational follow-ups and approval confirmations. |
| `frontend/src/App.tsx` | **UPDATE**: Render multi-step task execution progress and approval tickets. |

---

## 4. Definition of Done for Final Acceptance

The transformation is complete only when:
1. Natural spoken requests (English, Hindi, Hinglish) are understood without relying on exact regex phrases.
2. Ordinary questions produce direct conversational answers.
3. Actions (open app, adjust audio, search web) execute through typed tools with result verification.
4. KELA can find projects and files on computer drives and return exact absolute paths.
5. KELA can analyze RAM and disk storage, and recommend safe cleanups without deleting user files.
6. KELA can start supported projects on localhost, verify actual HTTP readiness, and return working URLs.
7. Pronouns (*"it"*, *"that file"*, *"run it"*) resolve correctly from conversation history.
8. Risky computer operations require explicit user approval.
9. All existing 119 unit tests continue to pass with 0 regressions.
10. The master documentation and test matrix are verified and submitted.
