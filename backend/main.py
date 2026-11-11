import asyncio
import base64
import hmac
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from action_policy import action_digest, audit_target
from agent import agent_stream, project_context_message
from connectors.registry import ConnectorRegistry
from database import (
    agent_task_cancellation_requested,
    create_agent_task,
    create_student_task,
    get_agent_task,
    get_connection,
    get_setting,
    get_student_task,
    initialize_database,
    list_agent_activity,
    list_student_tasks,
    record_agent_activity,
    request_agent_task_cancellation,
    save_message,
    set_setting,
    get_workspace_context as read_workspace_context,
    set_workspace_context as write_workspace_context,
    update_student_task,
)
from knowledge.engine import (
    delete_indexed_document,
    get_document_details,
    index_directory,
    index_file,
    list_indexed_documents,
    search_knowledge_base,
)
from memory.manager import MemoryManager
from pc_control import (
    launch_application,
    close_application,
    open_path,
    change_volume,
    set_volume,
    toggle_mute,
    get_system_metrics,
    list_running_processes,
    capture_desktop_screenshot,
    search_user_files,
)
from voice.router import dispatch_voice_command
from voice.providers import SpeechManager
speech_manager = SpeechManager()
from research.agent import research_stream
from browser.engine import BrowserAgent
from documents.processor import process_document
from github.agent import GitHubAgent
from github.client import GitHubClient, delete_github_token, save_github_token
from github.git_ops import get_repo_status
from image_gen.generator import ImageGenerationAgent
from orchestrator.router import (
    AutonomyLevel,
    Orchestrator,
    TaskCategory,
    classify_task_intent,
    get_current_autonomy_level,
    set_current_autonomy_level,
)
from vision.analyzer import VisionAgent
from workspace_tools import TOOL_SCHEMAS

# Local Ollama configuration
OLLAMA_URL = "http://127.0.0.1:11434"
MODEL_NAME = "qwen2.5-coder:7b"
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[1]
APPROVAL_TTL_SECONDS = 120


@dataclass
class ApprovalTicket:
    future: asyncio.Future[bool]
    action: str
    arguments: dict
    workspace: str
    action_digest: str
    risk: str
    target: str
    purpose: str
    reversible: bool
    alternatives: str
    expires_at: float
    task_id: str | None = None
    status: str = "pending"


APPROVALS: dict[str, ApprovalTicket] = {}
logger = logging.getLogger("nexus")
MAX_PROJECT_CONTEXT_LENGTH = 8000


def _record_approval_event(
    approval_id: str,
    ticket: ApprovalTicket,
    event: str,
) -> None:
    record_agent_activity(
        approval_id,
        ticket.action,
        ticket.risk,
        event,
        ticket.target,
        ticket.action_digest,
    )


def _register_approval(approval_id: str, details: dict) -> asyncio.Future[bool]:
    future = asyncio.get_running_loop().create_future()
    ticket = ApprovalTicket(
        future=future,
        action=details["action"],
        arguments=details["arguments"],
        workspace=details["workspace"],
        action_digest=details["action_digest"],
        risk=details["risk"],
        target=details["target"],
        purpose=details["purpose"],
        reversible=details["reversible"],
        alternatives=details["alternatives"],
        expires_at=time.monotonic() + APPROVAL_TTL_SECONDS,
        task_id=details.get("task_id"),
    )
    if approval_id in APPROVALS:
        raise ValueError("Approval identifier collision")
    APPROVALS[approval_id] = ticket
    _record_approval_event(approval_id, ticket, "requested")
    return future


def _clear_approval(approval_id: str) -> None:
    ticket = APPROVALS.pop(approval_id, None)
    if ticket is None:
        return
    if ticket.status in {"pending", "approved", "executing"}:
        ticket.status = (
            "expired" if time.monotonic() >= ticket.expires_at else "cancelled"
        )
        if not ticket.future.done():
            ticket.future.set_result(False)
        _record_approval_event(approval_id, ticket, ticket.status)


def _authorize_approval(
    approval_id: str,
    digest: str,
    action: str,
    arguments: dict,
    workspace: Path,
) -> bool:
    ticket = APPROVALS.get(approval_id)
    if ticket is None or ticket.status != "approved":
        return False
    actual_workspace = str(workspace.resolve(strict=True))
    actual_digest = action_digest(action, arguments, actual_workspace)
    if (
        time.monotonic() >= ticket.expires_at
        or not hmac.compare_digest(digest, ticket.action_digest)
        or not hmac.compare_digest(actual_digest, ticket.action_digest)
        or action != ticket.action
        or actual_workspace != ticket.workspace
    ):
        ticket.status = "mismatched"
        _record_approval_event(approval_id, ticket, "mismatched")
        return False
    ticket.status = "executing"
    _record_approval_event(approval_id, ticket, "executing")
    return True


def _complete_approval(approval_id: str, outcome: str) -> None:
    ticket = APPROVALS.get(approval_id)
    if ticket is None or ticket.status != "executing":
        return
    ticket.status = outcome
    _record_approval_event(approval_id, ticket, outcome)


def _workspace() -> Path:
    configured = get_setting("workspace")
    candidate = Path(configured) if configured else DEFAULT_WORKSPACE
    try:
        path = candidate.resolve(strict=True)
    except OSError:
        logger.warning("Saved workspace is unavailable; using the project workspace.")
        path = DEFAULT_WORKSPACE
    return path


def _active_model() -> str:
    return get_setting("selected_model") or MODEL_NAME


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    app.state.workspace = _workspace()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            current_model = _active_model()
            installed = any(
                item.get("name") == current_model
                for item in response.json().get("models", [])
            )
        if not installed:
            logger.warning(
                "Ollama is reachable but model %s is not installed.", current_model
            )
    except httpx.HTTPError:
        logger.warning("Ollama is unavailable at startup; chat will not work yet.")
    try:
        yield
    finally:
        from local_server import stop_all_local_servers

        await stop_all_local_servers()


app = FastAPI(
    title="Nexus AI Local API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5175",
        "http://127.0.0.1:5175",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):(?:517[5-9]|51[89]\d)",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=20000)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Message content cannot be empty or whitespace only.")
        return value


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=50)
    conversation_id: int | None = None
    turn_id: str | None = Field(default=None, max_length=100)


class AgentRequest(ChatRequest):
    pass


class WorkspaceRequest(BaseModel):
    path: str = Field(min_length=1, max_length=2048)


class WorkspaceContextRequest(BaseModel):
    context: str = Field(max_length=MAX_PROJECT_CONTEXT_LENGTH)


class StudentTaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class StudentTaskUpdateRequest(BaseModel):
    completed: bool


class ApprovalRequest(BaseModel):
    approved: bool
    action_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ConversationTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class KnowledgeIndexFileRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    source_id: int | None = None


class KnowledgeIndexDirRequest(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    recursive: bool = True
    source_id: int | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    hybrid: bool = True


class KnowledgeUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class ConnectorCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    connector_type: str = Field(min_length=1, max_length=50)
    config: dict = Field(default_factory=dict)
    is_read_only: bool = True


class ConnectorQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    params: list = Field(default_factory=list)
    max_rows: int = Field(default=100, ge=1, le=1000)


class PreferenceRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(max_length=10000)
    category: str = Field(default="general", max_length=50)


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    conversation_id: int | None = None
    turn_id: str | None = None
    depth: str = Field(default="standard", pattern=r"^(quick|standard|deep)$")
    sources: list[str] | None = None


class ModelSelectRequest(BaseModel):
    model: str = Field(min_length=1, max_length=100)


class GitHubTokenRequest(BaseModel):
    token: str = Field(min_length=1)


class GitHubCloneRequest(BaseModel):
    clone_url: str = Field(min_length=1)
    directory_name: str = Field(min_length=1)


class GitHubCommitRequest(BaseModel):
    message: str = Field(min_length=1)
    files: list[str] | None = None


class GitHubPushRequest(BaseModel):
    remote: str = "origin"
    branch: str | None = None


class GitHubCreateRepoRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    private: bool = True
    auto_init: bool = True


class AutonomyLevelRequest(BaseModel):
    level: int = Field(ge=1, le=5)


class OrchestratorPlanRequest(BaseModel):
    query: str = Field(min_length=1)
    category: str | None = None
    autonomy_level: int | None = None
    has_image: bool = False
    has_document: bool = False


class OrchestratorExecuteRequest(BaseModel):
    query: str = Field(min_length=1)
    category: str | None = None
    autonomy_level: int | None = None
    conversation_id: int | None = None
    turn_id: str | None = None


class VisionAnalyzeRequest(BaseModel):
    image_base64: str = Field(min_length=1)
    prompt: str = "Describe what you see in this image in detail."
    model: str | None = None


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1)
    width: int = 800
    height: int = 600
    backend: str = "auto"


class BrowserNavigateRequest(BaseModel):
    url: str = Field(min_length=1)


class BrowserSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = 8


class DocumentProcessRequest(BaseModel):
    file_path: str = Field(min_length=1)


def _create_conversation(title: str) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title) VALUES (?)",
            (title[:200] or "New chat",),
        )
        return cursor.lastrowid


def _conversation_for_turn(
    request: ChatRequest, first_user_message: str
) -> tuple[int, str]:
    turn_id = request.turn_id or str(uuid.uuid4())
    title = " ".join(first_user_message.split())[:60] or "New chat"
    conversation_id = request.conversation_id
    if conversation_id is None:
        if request.turn_id:
            with get_connection() as connection:
                existing = connection.execute(
                    """
                    SELECT conversation_id FROM messages
                    WHERE client_message_id = ?
                    """,
                    (turn_id,),
                ).fetchone()
            conversation_id = existing["conversation_id"] if existing else None
        if conversation_id is None:
            conversation_id = _create_conversation(title)
    else:
        with get_connection() as connection:
            conversation = connection.execute(
                "SELECT id, title FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation["title"] == "New chat":
            with get_connection() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()[0]
                if count == 0:
                    connection.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title, conversation_id),
                    )

    try:
        save_message(
            conversation_id,
            "user",
            first_user_message,
            client_message_id=turn_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return conversation_id, turn_id


def ndjson(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


@app.get("/api/health")
async def health():
    current_model = _active_model()
    installed = False
    models_list = []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            models_list = [m.get("name") for m in models if m.get("name")]
            installed = any(m == current_model for m in models_list)
    except httpx.HTTPError:
        return {
            "status": "degraded",
            "service": "Nexus AI",
            "nexus": True,
            "model": current_model,
            "models": [],
            "model_installed": False,
            "ollama_reachable": False,
            "message": f"Start Ollama and make sure `{current_model}` is installed.",
        }

    return {
        "status": "ok" if installed else "degraded",
        "service": "Nexus AI",
        "nexus": True,
        "model": current_model,
        "models": models_list,
        "model_installed": installed,
        "ollama_reachable": True,
        "message": (
            "Ready."
            if installed
            else f"Run `ollama pull {current_model}` to install the configured model."
        ),
    }


@app.get("/api/models")
async def list_models():
    current_model = _active_model()
    models_list = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{OLLAMA_URL}/api/tags")
            if response.status_code == 200:
                models_list = [m.get("name") for m in response.json().get("models", [])]
    except Exception:
        pass
    return {"current_model": current_model, "installed_models": models_list}


@app.post("/api/models/select")
async def select_model(request: ModelSelectRequest):
    set_setting("selected_model", request.model)
    return {"selected_model": request.model}


@app.get("/api/student/tasks")
async def get_student_tasks():
    return {"tasks": list_student_tasks()}


@app.post("/api/student/tasks")
async def create_student_task_route(request: StudentTaskCreateRequest):
    try:
        task = create_student_task(request.title)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task": task}


@app.patch("/api/student/tasks/{task_id}")
async def update_student_task_route(task_id: int, request: StudentTaskUpdateRequest):
    task = update_student_task(task_id, request.completed)
    if task is None:
        raise HTTPException(status_code=404, detail="Student task not found")
    return {"task": task}


@app.get("/api/workspace")
async def get_workspace():
    return {
        "path": str(app.state.workspace),
        "permissions": {
            "inspection": "allowed",
            "file_writes": "approval_required",
            "commands": "approval_required",
            "git_commits": "approval_required",
        },
    }


@app.post("/api/workspace")
async def select_workspace(request: WorkspaceRequest):
    try:
        selected = Path(request.path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail="Workspace directory does not exist") from exc
    if not selected.is_dir():
        raise HTTPException(status_code=400, detail="Workspace must be a directory")
    if selected == Path(selected.anchor):
        raise HTTPException(
            status_code=400,
            detail="Selecting a filesystem root is not allowed; choose a project directory.",
        )
    set_setting("workspace", str(selected))
    app.state.workspace = selected
    return await get_workspace()


def _selected_workspace_path() -> str:
    workspace = getattr(app.state, "workspace", DEFAULT_WORKSPACE)
    return str(Path(workspace).resolve(strict=True))


@app.get("/api/workspace/context")
async def get_selected_workspace_context():
    return {"context": read_workspace_context(_selected_workspace_path())}


@app.put("/api/workspace/context")
async def update_selected_workspace_context(request: WorkspaceContextRequest):
    write_workspace_context(_selected_workspace_path(), request.context)
    return await get_selected_workspace_context()


@app.get("/api/agent/tools")
async def agent_tool_schemas():
    return {"tools": TOOL_SCHEMAS}


@app.post("/api/agent/approval/{approval_id}")
async def decide_agent_approval(approval_id: str, request: ApprovalRequest):
    ticket = APPROVALS.get(approval_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="Approval request is no longer pending")
    if ticket.status != "pending":
        raise HTTPException(status_code=409, detail="Approval request was already decided")
    if time.monotonic() >= ticket.expires_at:
        ticket.status = "expired"
        if not ticket.future.done():
            ticket.future.set_result(False)
        _record_approval_event(approval_id, ticket, "expired")
        raise HTTPException(status_code=410, detail="Approval request has expired")
    if not hmac.compare_digest(request.action_digest, ticket.action_digest):
        _record_approval_event(approval_id, ticket, "digest_mismatch")
        raise HTTPException(status_code=409, detail="Approval does not match the requested action")
    ticket.status = "approved" if request.approved else "denied"
    _record_approval_event(approval_id, ticket, ticket.status)
    ticket.future.set_result(request.approved)
    return {"accepted": True}


@app.get("/api/agent/activity")
async def agent_activity(limit: int = 50):
    return {"events": list_agent_activity(max(1, min(limit, 100)))}


@app.get("/api/agent/servers")
async def agent_servers():
    from local_server import list_local_servers

    return {
        "servers": list_local_servers(
            Path(getattr(app.state, "workspace", DEFAULT_WORKSPACE)).resolve(strict=True)
        )
    }


@app.post("/api/agent/servers/{server_id}/stop")
async def stop_agent_server(server_id: str):
    from local_server import list_local_servers, stop_local_server

    workspace = Path(
        getattr(app.state, "workspace", DEFAULT_WORKSPACE)
    ).resolve(strict=True)
    if not any(
        server["id"] == server_id
        for server in list_local_servers(workspace)
    ):
        raise HTTPException(status_code=404, detail="Local server not found")
    await stop_local_server(server_id)
    return {"stopped": True, "id": server_id}


@app.get("/api/agent/tasks/{task_id}")
async def agent_task(task_id: str):
    task = get_agent_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    return task


@app.post("/api/agent/tasks/{task_id}/cancel")
async def cancel_agent_task(task_id: str):
    task = request_agent_task_cancellation(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    if task["state"] in {"completed", "blocked", "cancelled"}:
        raise HTTPException(status_code=409, detail="Agent task is already terminal")
    for approval_id, ticket in list(APPROVALS.items()):
        if ticket.task_id == task_id and ticket.status == "pending":
            ticket.status = "denied"
            if not ticket.future.done():
                ticket.future.set_result(False)
            _record_approval_event(approval_id, ticket, "cancelled")
    return task


# =========================================================================
# CONVERSATIONS ROUTES
# =========================================================================

@app.post("/api/conversations")
async def create_conversation(
    title: str = Body(default="New chat", embed=True),
):
    clean_title = title.strip()[:200] or "New chat"

    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title) VALUES (?)",
            (clean_title,),
        )
        conversation_id = cursor.lastrowid

    return {
        "id": conversation_id,
        "title": clean_title,
        "messages": [],
    }


@app.get("/api/conversations")
async def list_conversations():
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT c.id, c.title, c.created_at, c.updated_at,
                   COUNT(m.id) AS message_count
            FROM conversations c
            LEFT JOIN messages m ON m.conversation_id = c.id
            GROUP BY c.id
            ORDER BY c.updated_at DESC, c.id DESC
            """
        ).fetchall()

    return [dict(row) for row in rows]


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int):
    with get_connection() as connection:
        conversation = connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()

        if conversation is None:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )

        messages = connection.execute(
            """
            SELECT id, role, content, created_at, client_message_id
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        ).fetchall()

    return {
        "conversation": dict(conversation),
        "messages": [dict(row) for row in messages],
    }


@app.patch("/api/conversations/{conversation_id}")
async def rename_conversation(conversation_id: int, request: ConversationTitleRequest):
    clean_title = request.title.strip()[:200]
    with get_connection() as connection:
        cursor = connection.execute(
            "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (clean_title, conversation_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found")
    return {"id": conversation_id, "title": clean_title}


@app.delete("/api/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM conversations WHERE id = ?",
            (conversation_id,),
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Conversation not found",
            )

    return {"deleted": True, "id": conversation_id}


@app.get("/api/conversations/{conversation_id}/export")
async def export_conversation(conversation_id: int, format: str = "markdown"):
    with get_connection() as connection:
        conv = connection.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = connection.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()

    if format.lower() == "json":
        data = {
            "id": conv["id"],
            "title": conv["title"],
            "created_at": conv["created_at"],
            "updated_at": conv["updated_at"],
            "messages": [dict(m) for m in messages],
        }
        return data

    # Markdown format
    lines = [
        f"# {conv['title']}",
        f"*Exported from Nexus AI on {time.strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "---",
        "",
    ]
    for msg in messages:
        sender = "User" if msg["role"] == "user" else "Nexus AI"
        lines.append(f"### {sender} ({msg['created_at']})")
        lines.append(msg["content"])
        lines.append("")
        lines.append("---")
        lines.append("")

    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


# =========================================================================
# KNOWLEDGE ENGINE ROUTES
# =========================================================================

@app.get("/api/knowledge/documents")
async def get_knowledge_documents():
    return {"documents": list_indexed_documents()}


@app.get("/api/knowledge/documents/{doc_id}")
async def get_knowledge_document_route(doc_id: int):
    doc = get_document_details(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": doc}


@app.delete("/api/knowledge/documents/{doc_id}")
async def delete_knowledge_document_route(doc_id: int):
    success = delete_indexed_document(doc_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True, "id": doc_id}


@app.post("/api/knowledge/index-file")
async def index_knowledge_file(request: KnowledgeIndexFileRequest):
    try:
        res = index_file(request.path, source_id=request.source_id)
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/knowledge/index-directory")
async def index_knowledge_directory(request: KnowledgeIndexDirRequest):
    try:
        res = index_directory(request.path, source_id=request.source_id, recursive=request.recursive)
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/knowledge/search")
async def search_knowledge(request: KnowledgeSearchRequest):
    results = search_knowledge_base(request.query, top_k=request.top_k, hybrid=request.hybrid)
    return {"results": results, "count": len(results)}


@app.post("/api/knowledge/upload")
async def upload_and_index_document(request: KnowledgeUploadRequest):
    # Safe storage directory for uploaded documents inside the selected workspace
    storage_dir = Path(app.state.workspace) / ".nexus_uploads"
    storage_dir.mkdir(parents=True, exist_ok=True)
    target_path = storage_dir / Path(request.filename).name

    try:
        if request.content.startswith("data:") and ";base64," in request.content:
            _, b64 = request.content.split(";base64,", 1)
            raw = base64.b64decode(b64)
            target_path.write_bytes(raw)
        else:
            target_path.write_text(request.content, encoding="utf-8")

        res = index_file(target_path)
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Upload indexing failed: {exc}") from exc


# =========================================================================
# DATABASE CONNECTORS ROUTES
# =========================================================================

@app.get("/api/connectors")
async def list_connectors_route():
    return {"connectors": ConnectorRegistry.list_all()}


@app.post("/api/connectors")
async def create_connector_route(request: ConnectorCreateRequest):
    try:
        conn = ConnectorRegistry.register(
            request.id,
            request.name,
            request.connector_type,
            request.config,
            request.is_read_only,
        )
        return {"connector": {
            "id": conn.id,
            "name": conn.name,
            "connector_type": conn.connector_type,
            "is_read_only": conn.is_read_only,
        }}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/connectors/{connector_id}/test")
async def test_connector_route(connector_id: str):
    conn = ConnectorRegistry.get(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    return conn.test_connection()


@app.get("/api/connectors/{connector_id}/schema")
async def schema_connector_route(connector_id: str):
    conn = ConnectorRegistry.get(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    return conn.inspect_schema()


@app.post("/api/connectors/{connector_id}/query")
async def query_connector_route(connector_id: str, request: ConnectorQueryRequest):
    conn = ConnectorRegistry.get(connector_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connector not found")
    try:
        return conn.execute_query(request.query, request.params, request.max_rows)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/connectors/{connector_id}")
async def delete_connector_route(connector_id: str):
    try:
        success = ConnectorRegistry.remove(connector_id)
        if not success:
            raise HTTPException(status_code=404, detail="Connector not found")
        return {"deleted": True, "id": connector_id}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# =========================================================================
# MEMORY & PREFERENCES ROUTES
# =========================================================================

@app.get("/api/memory/preferences")
async def get_preferences_route():
    return {"preferences": MemoryManager.get_preferences()}


@app.put("/api/memory/preferences")
async def set_preference_route(request: PreferenceRequest):
    MemoryManager.set_preference(request.key, request.value, request.category)
    return {"saved": True, "key": request.key, "value": request.value}


@app.delete("/api/memory/preferences/{key}")
async def delete_preference_route(key: str):
    success = MemoryManager.remove_preference(key)
    return {"deleted": success, "key": key}


@app.get("/api/memory/export")
async def export_memory_route():
    return MemoryManager.export_snapshot()


@app.post("/api/memory/clear")
async def clear_memory_route():
    MemoryManager.clear_memory()
    return {"cleared": True}


# =========================================================================
# RESEARCH AGENT ROUTE
# =========================================================================

@app.post("/api/research")
async def run_research(request: ResearchRequest):
    if not request.query.strip():
        raise HTTPException(status_code=400, detail="Research query cannot be empty.")

    first_user_message = request.query.strip()
    chat_req = ChatRequest(
        messages=[Message(role="user", content=first_user_message)],
        conversation_id=request.conversation_id,
        turn_id=request.turn_id,
    )
    conversation_id, turn_id = _conversation_for_turn(chat_req, first_user_message)
    workspace_path = _selected_workspace_path()
    current_model = _active_model()

    return StreamingResponse(
        research_stream(
            query=request.query,
            conversation_id=conversation_id,
            turn_id=turn_id,
            workspace_path=workspace_path,
            depth=request.depth,
            sources=request.sources,
            model_name=current_model,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# GITHUB INTEGRATION ROUTES
# =========================================================================

@app.post("/api/github/token")
async def save_github_token_route(req: GitHubTokenRequest):
    save_github_token(req.token)
    client = GitHubClient(req.token)
    return await client.verify_token()


@app.get("/api/github/status")
async def get_github_status_route():
    agent = GitHubAgent(workspace_path=str(_selected_workspace_path()))
    return await agent.get_status()


@app.delete("/api/github/token")
async def delete_github_token_route():
    delete_github_token()
    return {"disconnected": True}


@app.get("/api/github/repos")
async def list_github_repos_route(search: str | None = None):
    client = GitHubClient()
    if search and search.strip():
        return await client.search_repositories(search.strip())
    return await client.list_repositories()


@app.get("/api/github/repo/{owner}/{repo}")
async def inspect_github_repo_route(owner: str, repo: str):
    agent = GitHubAgent()
    return await agent.inspect_repository(owner, repo)


@app.post("/api/github/clone")
async def clone_github_repo_route(req: GitHubCloneRequest):
    agent = GitHubAgent(workspace_path=str(_selected_workspace_path()))
    return agent.clone_to_workspace(req.clone_url, req.directory_name)


@app.post("/api/github/commit")
async def commit_github_repo_route(req: GitHubCommitRequest):
    agent = GitHubAgent(workspace_path=str(_selected_workspace_path()))
    return agent.commit_workspace(req.message, req.files)


@app.post("/api/github/push")
async def push_github_repo_route(req: GitHubPushRequest):
    agent = GitHubAgent(workspace_path=str(_selected_workspace_path()))
    return agent.push_workspace(remote=req.remote, branch=req.branch)


@app.post("/api/github/create-repo")
async def create_github_repo_route(req: GitHubCreateRepoRequest):
    client = GitHubClient()
    return await client.create_repository(
        name=req.name,
        description=req.description,
        private=req.private,
        auto_init=req.auto_init,
    )


# =========================================================================
# ORCHESTRATOR & AUTONOMY ROUTES
# =========================================================================

@app.get("/api/orchestrator/autonomy")
async def get_autonomy_route():
    return {"level": get_current_autonomy_level()}


@app.post("/api/orchestrator/autonomy")
async def set_autonomy_route(req: AutonomyLevelRequest):
    set_current_autonomy_level(req.level)
    return {"level": req.level}


@app.post("/api/orchestrator/plan")
async def create_orchestrator_plan_route(req: OrchestratorPlanRequest):
    category = None
    if req.category:
        try:
            category = TaskCategory(req.category)
        except ValueError:
            pass
    if not category:
        category = classify_task_intent(
            req.query,
            has_image=req.has_image,
            has_document=req.has_document,
        )

    autonomy = req.autonomy_level or get_current_autonomy_level()
    orchestrator = Orchestrator(str(_selected_workspace_path()))
    return orchestrator.create_plan(req.query, category, autonomy)


@app.post("/api/orchestrator/execute")
async def execute_orchestrated_task_route(req: OrchestratorExecuteRequest):
    category = None
    if req.category:
        try:
            category = TaskCategory(req.category)
        except ValueError:
            pass
    if not category:
        category = classify_task_intent(req.query)

    autonomy = req.autonomy_level or get_current_autonomy_level()
    workspace_path = _selected_workspace_path()
    orchestrator = Orchestrator(str(workspace_path))

    first_user_message = req.query.strip()
    chat_req = ChatRequest(
        messages=[Message(role="user", content=first_user_message)],
        conversation_id=req.conversation_id,
        turn_id=req.turn_id,
    )
    conv_id, turn_id = _conversation_for_turn(chat_req, first_user_message)

    return StreamingResponse(
        orchestrator.execute_orchestrated_stream(
            query=req.query,
            category=category,
            autonomy_level=autonomy,
            conversation_id=conv_id,
            turn_id=turn_id,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# VISION AGENT ROUTES
# =========================================================================

@app.get("/api/vision/models")
async def get_vision_models_route():
    agent = VisionAgent()
    models = await agent.detect_available_vision_models()
    return {"models": models}


@app.post("/api/vision/analyze")
async def analyze_vision_route(req: VisionAnalyzeRequest):
    try:
        raw_bytes = base64.b64decode(req.image_base64)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64 image data: {exc}")

    agent = VisionAgent()
    return await agent.analyze_image(
        raw_bytes,
        prompt=req.prompt,
        model_name=req.model,
    )


# =========================================================================
# IMAGE GENERATION ROUTES
# =========================================================================

@app.get("/api/image-gen/backends")
async def get_image_backends_route():
    agent = ImageGenerationAgent(str(_selected_workspace_path()))
    return await agent.detect_backends()


@app.post("/api/image-gen/generate")
async def generate_image_route(req: ImageGenerateRequest):
    agent = ImageGenerationAgent(str(_selected_workspace_path()))
    return await agent.generate_image(
        prompt=req.prompt,
        width=req.width,
        height=req.height,
        backend=req.backend,
    )


@app.get("/api/image-gen/gallery")
async def get_image_gallery_route():
    agent = ImageGenerationAgent(str(_selected_workspace_path()))
    return agent.list_gallery()


@app.delete("/api/image-gen/gallery/{image_id}")
async def delete_gallery_image_route(image_id: str):
    agent = ImageGenerationAgent(str(_selected_workspace_path()))
    success = agent.delete_image(image_id)
    return {"deleted": success}


# =========================================================================
# BROWSER AGENT ROUTES
# =========================================================================

@app.post("/api/browser/navigate")
async def browser_navigate_route(req: BrowserNavigateRequest):
    agent = BrowserAgent()
    return await agent.navigate(req.url)


@app.post("/api/browser/search")
async def browser_search_route(req: BrowserSearchRequest):
    agent = BrowserAgent()
    results = await agent.search(req.query, limit=req.limit)
    return {"results": results}


# =========================================================================
# ADVANCED DOCUMENT INTELLIGENCE ROUTES
# =========================================================================

@app.post("/api/documents/process")
async def process_document_route(req: DocumentProcessRequest):
    target = Path(req.file_path)
    if not target.is_absolute():
        target = _selected_workspace_path() / target
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {target}")

    try:
        return process_document(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# =========================================================================
# CHAT ROUTE
# =========================================================================

@app.post("/api/chat")
async def chat(request: ChatRequest):
    if not any(message.role == "user" for message in request.messages):
        raise HTTPException(
            status_code=400,
            detail="A user message is required",
        )

    last_user_message = next(
        message.content
        for message in reversed(request.messages)
        if message.role == "user"
    )

    conversation_id, turn_id = _conversation_for_turn(
        request, last_user_message
    )

    model_messages = [
        message.model_dump() for message in request.messages
    ]
    
    # Inject workspace context
    project_context = read_workspace_context(_selected_workspace_path())
    context_message = project_context_message(project_context)
    if context_message:
        model_messages.insert(0, context_message)

    # Inject persistent user preferences if configured
    user_prefs = MemoryManager.get_preferences()
    if user_prefs:
        pref_lines = [f"- {k}: {v}" for k, v in user_prefs.items()]
        model_messages.insert(
            0,
            {
                "role": "system",
                "content": (
                    "User persistent preferences for responses:\n"
                    + "\n".join(pref_lines)
                ),
            },
        )

    current_model = _active_model()

    async def generate():
        assistant_parts = []

        # The frontend can capture this event to remember the conversation.
        yield ndjson({
            "conversation_id": conversation_id,
        })

        def _add_evidence_msg(content: str):
            if model_messages and model_messages[0].get("role") == "system":
                model_messages.insert(1, {"role": "system", "content": content})
            else:
                model_messages.insert(0, {"role": "system", "content": content})

        # 1. Automatic Live Web Browsing if user prompt contains URL
        urls = re.findall(r"https?://[^\s<>\"']+", last_user_message)
        if urls:
            from browser.engine import BrowserAgent
            browser = BrowserAgent()
            for target_url in urls[:2]:
                yield ndjson({"step": f"Browsing live website: {target_url}..."})
                try:
                    res = await browser.navigate(target_url)
                    if res.get("success") and res.get("page"):
                        page = res["page"]
                        page_title = page.get("title", target_url)
                        page_text = page.get("text_preview", "")
                        yield ndjson({"step": f"Extracted content from '{page_title}' ({len(page_text)} chars)"})
                        _add_evidence_msg(
                            f"[Live Web Evidence from {target_url}]\n"
                            f"Title: {page_title}\n"
                            f"Description: {page.get('description', '')}\n"
                            f"Extracted Page Content:\n{page_text[:7000]}\n"
                            "Analyze and directly use this real-time webpage content to answer the user's questions in full detail."
                        )
                except Exception as exc:
                    logger.warning("Auto-browse failed for %s: %s", target_url, exc)

        # 2. Automatic Document Intelligence if user prompt references attachments
        att_matches = re.findall(r"\[Referenced Attachments:\s*([^\]]+)\]", last_user_message)
        if att_matches:
            from documents.processor import process_document
            storage_dir = Path(app.state.workspace) / ".nexus_uploads"
            for att_line in att_matches:
                file_names = [f.strip() for f in att_line.split(",") if f.strip()]
                for fname in file_names:
                    candidate_paths = [
                        storage_dir / fname,
                        Path(app.state.workspace) / fname,
                        Path.home() / "Downloads" / fname,
                    ]
                    target_file = next((p for p in candidate_paths if p.is_file()), None)
                    if target_file:
                        try:
                            doc_info = process_document(target_file)
                            doc_content = doc_info.get("content", "")
                            if doc_content:
                                total_units = doc_info.get("total_slides", doc_info.get("total_pages", "structured"))
                                yield ndjson({"step": f"Analyzed attachment '{fname}' ({total_units} sections)"})
                                _add_evidence_msg(
                                    f"[Document Intelligence - Content of Attached '{fname}']\n"
                                    f"Type: {doc_info.get('document_type', 'document')}\n"
                                    f"Content:\n{doc_content[:12000]}\n"
                                    "Thoroughly analyze this attached document content to fulfill the user's instructions (e.g. pros and cons, summary, slide analysis, technical review)."
                                )
                        except Exception as exc:
                            logger.warning("Failed to auto-process attachment %s: %s", fname, exc)

        # 3. Nexus AI System Persona
        _add_evidence_msg(
            "You are Nexus AI, an autonomous Personal AI Operating System. "
            "You have integrated live web browsing, document intelligence (PDF, PPTX, DOCX, XLSX), "
            "local coding tools, and workspace execution. "
            "Never say you cannot browse the internet or access documents when web evidence or document contents are provided. "
            "Always deliver clear, structured, well-grounded, professional responses."
        )

        payload = {
            "model": current_model,
            "messages": model_messages,
            "stream": True,
            "options": {"num_ctx": 8192, "num_predict": 2048},
        }

        try:
            timeout = httpx.Timeout(
                connect=10.0,
                read=300.0,
                write=30.0,
                pool=10.0,
            )

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{OLLAMA_URL}/api/chat",
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line:
                            continue

                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            yield ndjson({
                                "error": "Received invalid data from Ollama",
                            })
                            return

                        if event.get("error"):
                            yield ndjson({
                                "error": str(event["error"]),
                            })
                            return

                        content = event.get("message", {}).get(
                            "content", ""
                        )

                        if content:
                            assistant_parts.append(content)
                            yield ndjson({"token": content})

                        if event.get("done"):
                            answer = "".join(assistant_parts)

                            if answer:
                                save_message(
                                    conversation_id,
                                    "assistant",
                                    answer,
                                    client_message_id=f"{turn_id}:assistant",
                                )

                            yield ndjson({
                                "done": True,
                                "model": current_model,
                                "conversation_id": conversation_id,
                            })
                            return

                    yield ndjson({
                        "error": "Ollama ended the stream unexpectedly",
                    })

        except httpx.TimeoutException:
            yield ndjson({
                "error": "The model timed out. Try a shorter prompt.",
            })
        except httpx.HTTPStatusError as exc:
            yield ndjson({
                "error": (
                    f"Ollama returned HTTP "
                    f"{exc.response.status_code}. Check the local model service."
                ),
            })
        except httpx.HTTPError:
            yield ndjson({
                "error": "Could not communicate with Ollama",
            })
        except ValueError:
            yield ndjson({"error": "Could not save the completed response."})
        except Exception:
            logger.exception("Unexpected error while streaming a chat response.")
            yield ndjson({"error": "Unexpected error while completing the response."})

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# CODING AGENT ROUTE
# =========================================================================

@app.post("/api/agent")
async def run_agent(request: AgentRequest):
    user_messages = [
        message for message in request.messages if message.role == "user"
    ]
    if not user_messages:
        raise HTTPException(status_code=400, detail="A user message is required")
    last_user_message = user_messages[-1].content
    conversation_id, turn_id = _conversation_for_turn(
        request, last_user_message
    )
    messages = [
        message.model_dump()
        for message in request.messages
        if message.role in {"user", "assistant"}
    ]
    root = Path(app.state.workspace)
    project_context = read_workspace_context(_selected_workspace_path())
    task_id = str(uuid.uuid4())
    create_agent_task(
        task_id,
        conversation_id,
        last_user_message,
        str(root.resolve(strict=True)),
    )

    return StreamingResponse(
        agent_stream(
            root=root,
            conversation_id=conversation_id,
            messages=messages,
            turn_id=turn_id,
            register_approval=_register_approval,
            clear_approval=_clear_approval,
            authorize_approval=_authorize_approval,
            complete_approval=_complete_approval,
            record_activity=record_agent_activity,
            task_id=task_id,
            project_context=project_context,
        ),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


# =========================================================================
# KELA PC CONTROL & VOICE DISPATCH ROUTES
# =========================================================================

class PCLaunchRequest(BaseModel):
    app: str

class PCVolumeRequest(BaseModel):
    action: str  # "up", "down", "mute", "set"
    level: int | None = None
    steps: int | None = 5

class PCSearchRequest(BaseModel):
    query: str
    max_results: int | None = 15

class VoiceCommandRequest(BaseModel):
    text: str

class VoiceSpeakRequest(BaseModel):
    text: str
    voice: Optional[str] = None

@app.get("/api/voice/hardware")
async def voice_hardware_endpoint():
    """Report hardware audio, STT, and TTS provider capabilities."""
    return speech_manager.get_hardware_status()

@app.post("/api/voice/speak")
async def voice_speak_endpoint(req: VoiceSpeakRequest):
    """Local text-to-speech execution via native Windows SAPI."""
    return speech_manager.windows_tts.synthesize(req.text, req.voice)

@app.post("/api/voice/command")
@app.post("/api/voice/conversation")
async def voice_command_endpoint(req: VoiceCommandRequest):
    """Voice mode conversation & action dispatcher with spoken response generation."""
    return await dispatch_voice_command(req.text)

@app.post("/api/pc/launch")
async def pc_launch_endpoint(req: PCLaunchRequest):
    """Launch a Windows application or URI."""
    return launch_application(req.app)

@app.post("/api/pc/close")
async def pc_close_endpoint(req: PCLaunchRequest):
    """Close a Windows application by name."""
    return close_application(req.app)

@app.post("/api/pc/volume")
async def pc_volume_endpoint(req: PCVolumeRequest):
    """Adjust or mute Windows volume."""
    act = req.action.lower()
    if act == "up":
        return change_volume("up", req.steps or 5)
    elif act == "down":
        return change_volume("down", req.steps or 5)
    elif act == "mute":
        return toggle_mute()
    elif act == "set":
        return set_volume(req.level if req.level is not None else 50)
    else:
        raise HTTPException(status_code=400, detail="Invalid volume action")

@app.get("/api/pc/system")
async def pc_system_endpoint():
    """Get real-time CPU, RAM, and Battery diagnostics."""
    return get_system_metrics()

@app.get("/api/pc/processes")
async def pc_processes_endpoint(limit: int = 20):
    """List top running processes by memory."""
    return list_running_processes(limit)

@app.post("/api/pc/screenshot")
async def pc_screenshot_endpoint():
    """Capture a primary desktop screenshot."""
    res = capture_desktop_screenshot()
    if res.get("status") != "success":
        raise HTTPException(status_code=500, detail=res.get("message", "Screenshot failed"))
    return res

@app.post("/api/pc/search")
async def pc_search_endpoint(req: PCSearchRequest):
    """Fast search for files in Documents, Downloads, and Desktop."""
    return search_user_files(req.query, req.max_results or 15)
