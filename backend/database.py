import os
import sqlite3
import json
from pathlib import Path

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parent / "nexus_ai.db"
DATABASE_PATH = Path(os.environ.get("NEXUS_DB_PATH", DEFAULT_DATABASE_PATH))
TASK_TRANSITIONS = {
    "queued": {"planning", "cancelled", "blocked"},
    "planning": {"inspecting", "cancelled", "blocked"},
    "inspecting": {"implementing", "verifying", "completed", "cancelled", "blocked"},
    "implementing": {"inspecting", "verifying", "cancelled", "blocked"},
    "verifying": {"repairing", "inspecting", "completed", "cancelled", "blocked"},
    "repairing": {"implementing", "inspecting", "verifying", "cancelled", "blocked"},
    "completed": set(),
    "blocked": set(),
    "cancelled": set(),
}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT 'New chat',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (
                    role IN ('user', 'assistant', 'system')
                ),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS student_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS workspace_contexts (
                workspace_path TEXT PRIMARY KEY,
                context TEXT NOT NULL CHECK (length(context) <= 8000),
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                risk TEXT NOT NULL,
                event TEXT NOT NULL,
                target TEXT NOT NULL DEFAULT '',
                action_digest TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                conversation_id INTEGER NOT NULL,
                goal TEXT NOT NULL,
                workspace_path TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'queued' CHECK (state IN (
                    'queued', 'planning', 'inspecting', 'implementing',
                    'verifying', 'repairing', 'completed', 'blocked', 'cancelled'
                )),
                progress_json TEXT NOT NULL DEFAULT '[]',
                changed_files_json TEXT NOT NULL DEFAULT '[]',
                tool_results_json TEXT NOT NULL DEFAULT '[]',
                verification_status TEXT NOT NULL DEFAULT 'not_required'
                    CHECK (verification_status IN ('not_required', 'pending', 'verified', 'failed')),
                cancellation_requested INTEGER NOT NULL DEFAULT 0
                    CHECK (cancellation_requested IN (0, 1)),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_tasks_updated
            ON agent_tasks(updated_at DESC)
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_agent_activity_created
            ON agent_activity(id DESC)
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, id)
        """)

        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(messages)")
        }
        if "client_message_id" not in columns:
            connection.execute(
                "ALTER TABLE messages ADD COLUMN client_message_id TEXT"
            )
        connection.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_client_id
            ON messages(conversation_id, client_message_id)
            WHERE client_message_id IS NOT NULL
        """)

        # Knowledge Engine tables
        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                source_type TEXT NOT NULL,
                path TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id INTEGER,
                file_path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'indexed',
                error_message TEXT,
                FOREIGN KEY (source_id) REFERENCES knowledge_sources(id) ON DELETE SET NULL
            )
        """)
        connection.execute("""
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                token_count INTEGER NOT NULL DEFAULT 0,
                start_line INTEGER,
                end_line INTEGER,
                embedding_json TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (document_id) REFERENCES knowledge_documents(id) ON DELETE CASCADE
            )
        """)
        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_doc
            ON knowledge_chunks(document_id, chunk_index)
        """)

        try:
            connection.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts USING fts5(
                    content,
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    title UNINDEXED,
                    file_path UNINDEXED
                )
            """)
        except sqlite3.OperationalError:
            pass

        # Database Connectors table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS database_connectors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                connector_type TEXT NOT NULL,
                config_json TEXT NOT NULL,
                is_read_only INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # User Preferences / Persistent Memory table
        connection.execute("""
            CREATE TABLE IF NOT EXISTS user_preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def get_setting(key: str) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM app_settings WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def get_workspace_context(workspace_path: str) -> str:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT context FROM workspace_contexts WHERE workspace_path = ?",
            (workspace_path,),
        ).fetchone()
    return row["context"] if row else ""


def set_workspace_context(workspace_path: str, context: str) -> None:
    with get_connection() as connection:
        if not context.strip():
            connection.execute(
                "DELETE FROM workspace_contexts WHERE workspace_path = ?",
                (workspace_path,),
            )
            return
        connection.execute(
            """
            INSERT INTO workspace_contexts (workspace_path, context)
            VALUES (?, ?)
            ON CONFLICT(workspace_path) DO UPDATE SET
                context = excluded.context,
                updated_at = CURRENT_TIMESTAMP
            """,
            (workspace_path, context),
        )


def list_student_tasks() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM student_tasks
            ORDER BY completed ASC, created_at DESC
            """,
        ).fetchall()
    return [dict(row) for row in rows]


def get_student_task(task_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM student_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def create_student_task(title: str) -> dict:
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("Task title is required")
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO student_tasks (title) VALUES (?)",
            (cleaned,),
        )
    return get_student_task(cursor.lastrowid)


def update_student_task(task_id: int, completed: bool) -> dict | None:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE student_tasks
            SET completed = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if completed else 0, task_id),
        )
    if cursor.rowcount == 0:
        return None
    return get_student_task(task_id)


def record_agent_activity(
    activity_id: str,
    action: str,
    risk: str,
    event: str,
    target: str,
    digest: str,
) -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_activity
                (activity_id, action, risk, event, target, action_digest)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (activity_id, action, risk, event, target, digest),
        )


def list_agent_activity(limit: int = 50) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT activity_id, action, risk, event, target, created_at
            FROM agent_activity
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def _task_from_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    task = dict(row)
    for column, key in (
        ("progress_json", "progress"),
        ("changed_files_json", "changed_files"),
        ("tool_results_json", "tool_results"),
    ):
        task[key] = json.loads(task.pop(column))
    task["cancellation_requested"] = bool(task["cancellation_requested"])
    return task


def create_agent_task(
    task_id: str,
    conversation_id: int,
    goal: str,
    workspace_path: str,
) -> dict:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO agent_tasks (id, conversation_id, goal, workspace_path)
            VALUES (?, ?, ?, ?)
            """,
            (task_id, conversation_id, goal, workspace_path),
        )
    return get_agent_task(task_id)


def get_agent_task(task_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM agent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    return _task_from_row(row)


def _append_task_json(task_id: str, column: str, value: object) -> None:
    if column not in {"progress_json", "changed_files_json", "tool_results_json"}:
        raise ValueError("Unsupported task field")
    with get_connection() as connection:
        row = connection.execute(
            f"SELECT {column} FROM agent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Agent task not found")
        values = json.loads(row[column])
        values.append(value)
        connection.execute(
            f"""
            UPDATE agent_tasks
            SET {column} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (json.dumps(values, ensure_ascii=False), task_id),
        )


def transition_agent_task(task_id: str, state: str, message: str = "") -> dict:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT state FROM agent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Agent task not found")
        current = row["state"]
        if state != current and state not in TASK_TRANSITIONS.get(current, set()):
            raise ValueError(f"Invalid agent task transition: {current} -> {state}")
        connection.execute(
            """
            UPDATE agent_tasks
            SET state = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (state, task_id),
        )
    if message:
        _append_task_json(
            task_id,
            "progress_json",
            {"state": state, "message": message},
        )
    return get_agent_task(task_id)


def append_agent_task_progress(task_id: str, message: str) -> None:
    _append_task_json(
        task_id,
        "progress_json",
        {"message": message},
    )


def record_agent_task_tool_result(task_id: str, tool: str, output: str) -> None:
    _append_task_json(
        task_id,
        "tool_results_json",
        {"tool": tool, "output": output[:4000]},
    )


def record_agent_task_file_change(task_id: str, path: str) -> None:
    task = get_agent_task(task_id)
    if task is None:
        raise ValueError("Agent task not found")
    paths = task["changed_files"]
    if path not in paths:
        _append_task_json(task_id, "changed_files_json", path)
    with get_connection() as connection:
        connection.execute(
            """
            UPDATE agent_tasks
            SET verification_status = 'pending', updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (task_id,),
        )


def set_agent_task_verification(task_id: str, status: str) -> None:
    if status not in {"not_required", "pending", "verified", "failed"}:
        raise ValueError("Invalid verification status")
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_tasks
            SET verification_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, task_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("Agent task not found")


def request_agent_task_cancellation(task_id: str) -> dict | None:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            UPDATE agent_tasks
            SET cancellation_requested = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND state NOT IN ('completed', 'blocked', 'cancelled')
            """,
            (task_id,),
        )
    if cursor.rowcount:
        _append_task_json(
            task_id,
            "progress_json",
            {"message": "Cancellation requested."},
        )
    return get_agent_task(task_id)


def agent_task_cancellation_requested(task_id: str) -> bool:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT cancellation_requested FROM agent_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
    return bool(row and row["cancellation_requested"])


def save_message(
    conversation_id: int,
    role: str,
    content: str,
    client_message_id: str | None = None,
) -> bool:
    with get_connection() as connection:
        exists = connection.execute(
            "SELECT id FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        if exists is None:
            raise ValueError("Conversation not found")
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO messages
                (conversation_id, role, content, client_message_id)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, client_message_id),
        )
        if cursor.rowcount:
            connection.execute(
                """
                UPDATE conversations
                SET updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (conversation_id,),
            )
        return cursor.rowcount > 0


def create_conversation(title: str = "New chat") -> dict:
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (title) VALUES (?)",
            (title.strip() or "New chat",),
        )
        conv_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conv_id,),
        ).fetchone()
        return dict(row)


def get_conversation_by_id(conversation_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (conversation_id,),
        ).fetchone()
        return dict(row) if row else None


# =========================================================================
# KNOWLEDGE ENGINE DATA HELPERS
# =========================================================================

def create_knowledge_source(name: str, source_type: str, path: str = "") -> dict:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_sources (name, source_type, path)
            VALUES (?, ?, ?)
            """,
            (name.strip(), source_type.strip(), path.strip()),
        )
        source_id = cursor.lastrowid
        row = connection.execute(
            "SELECT * FROM knowledge_sources WHERE id = ?",
            (source_id,),
        ).fetchone()
    return dict(row)


def list_knowledge_sources() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM knowledge_sources ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def delete_knowledge_source(source_id: int) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM knowledge_sources WHERE id = ?",
            (source_id,),
        )
    return cursor.rowcount > 0


def upsert_knowledge_document(
    file_path: str,
    title: str,
    content_hash: str,
    mime_type: str,
    size_bytes: int,
    chunk_count: int,
    source_id: int | None = None,
    status: str = "indexed",
    error_message: str | None = None,
) -> int:
    with get_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_documents (
                file_path, title, content_hash, mime_type,
                size_bytes, chunk_count, source_id, status, error_message, indexed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_path) DO UPDATE SET
                title = excluded.title,
                content_hash = excluded.content_hash,
                mime_type = excluded.mime_type,
                size_bytes = excluded.size_bytes,
                chunk_count = excluded.chunk_count,
                source_id = coalesce(excluded.source_id, knowledge_documents.source_id),
                status = excluded.status,
                error_message = excluded.error_message,
                indexed_at = CURRENT_TIMESTAMP
            """,
            (
                file_path,
                title,
                content_hash,
                mime_type,
                size_bytes,
                chunk_count,
                source_id,
                status,
                error_message,
            ),
        )
        row = connection.execute(
            "SELECT id FROM knowledge_documents WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row["id"]


def get_knowledge_document_by_path(file_path: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM knowledge_documents WHERE file_path = ?",
            (file_path,),
        ).fetchone()
    return dict(row) if row else None


def get_knowledge_document(doc_id: int) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM knowledge_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
    return dict(row) if row else None


def list_knowledge_documents() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT d.*, s.name as source_name
            FROM knowledge_documents d
            LEFT JOIN knowledge_sources s ON d.source_id = s.id
            ORDER BY d.indexed_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def delete_knowledge_document(doc_id: int) -> bool:
    with get_connection() as connection:
        # Delete from FTS first
        try:
            connection.execute(
                "DELETE FROM knowledge_chunks_fts WHERE document_id = ?",
                (str(doc_id),),
            )
        except sqlite3.OperationalError:
            pass

        # Cascade deletes chunks
        cursor = connection.execute(
            "DELETE FROM knowledge_documents WHERE id = ?",
            (doc_id,),
        )
    return cursor.rowcount > 0


def save_knowledge_chunks(doc_id: int, chunks: list[dict]) -> None:
    with get_connection() as connection:
        # Remove old chunks for this document
        connection.execute(
            "DELETE FROM knowledge_chunks WHERE document_id = ?",
            (doc_id,),
        )
        try:
            connection.execute(
                "DELETE FROM knowledge_chunks_fts WHERE document_id = ?",
                (str(doc_id),),
            )
        except sqlite3.OperationalError:
            pass

        doc = connection.execute(
            "SELECT title, file_path FROM knowledge_documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        title = doc["title"] if doc else ""
        file_path = doc["file_path"] if doc else ""

        for chunk in chunks:
            cursor = connection.execute(
                """
                INSERT INTO knowledge_chunks (
                    document_id, chunk_index, content, token_count,
                    start_line, end_line, embedding_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    chunk.get("chunk_index", 0),
                    chunk["content"],
                    chunk.get("token_count", len(chunk["content"].split())),
                    chunk.get("start_line"),
                    chunk.get("end_line"),
                    json.dumps(chunk.get("embedding", [])),
                ),
            )
            chunk_id = cursor.lastrowid

            try:
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks_fts (
                        content, chunk_id, document_id, title, file_path
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (chunk["content"], str(chunk_id), str(doc_id), title, file_path),
                )
            except sqlite3.OperationalError:
                pass


def get_knowledge_chunks(doc_id: int) -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM knowledge_chunks
            WHERE document_id = ?
            ORDER BY chunk_index ASC
            """,
            (doc_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def search_knowledge_chunks_fts(query: str, limit: int = 10) -> list[dict]:
    # Clean query for FTS5 syntax
    sanitized_terms = [t for t in query.replace('"', "").replace("'", "").split() if t]
    if not sanitized_terms:
        return []
    fts_query = " OR ".join(sanitized_terms)

    with get_connection() as connection:
        try:
            rows = connection.execute(
                """
                SELECT fts.chunk_id, fts.document_id, fts.title, fts.file_path,
                       kc.content, kc.chunk_index, kc.start_line, kc.end_line,
                       rank as fts_rank
                FROM knowledge_chunks_fts fts
                JOIN knowledge_chunks kc ON kc.id = CAST(fts.chunk_id AS INTEGER)
                WHERE knowledge_chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            # Fallback to LIKE if FTS fails on punctuation
            like_term = f"%{sanitized_terms[0]}%"
            rows = connection.execute(
                """
                SELECT kc.id as chunk_id, kc.document_id, kd.title, kd.file_path,
                       kc.content, kc.chunk_index, kc.start_line, kc.end_line,
                       0.0 as fts_rank
                FROM knowledge_chunks kc
                JOIN knowledge_documents kd ON kd.id = kc.document_id
                WHERE kc.content LIKE ?
                LIMIT ?
                """,
                (like_term, limit),
            ).fetchall()
            return [dict(row) for row in rows]


def get_all_chunks_with_embeddings() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT kc.id as chunk_id, kc.document_id, kc.chunk_index,
                   kc.content, kc.start_line, kc.end_line, kc.embedding_json,
                   kd.title, kd.file_path
            FROM knowledge_chunks kc
            JOIN knowledge_documents kd ON kd.id = kc.document_id
            WHERE kc.embedding_json IS NOT NULL AND kc.embedding_json != '[]'
            """
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        try:
            item["embedding"] = json.loads(item.pop("embedding_json"))
        except Exception:
            item["embedding"] = []
        results.append(item)
    return results


# =========================================================================
# DATABASE CONNECTORS DATA HELPERS
# =========================================================================

def save_database_connector(
    connector_id: str,
    name: str,
    connector_type: str,
    config: dict,
    is_read_only: bool = True,
) -> dict:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO database_connectors (
                id, name, connector_type, config_json, is_read_only, updated_at
            )
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                connector_type = excluded.connector_type,
                config_json = excluded.config_json,
                is_read_only = excluded.is_read_only,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                connector_id,
                name.strip(),
                connector_type.strip().lower(),
                json.dumps(config, ensure_ascii=False),
                1 if is_read_only else 0,
            ),
        )
    return get_database_connector(connector_id)


def get_database_connector(connector_id: str) -> dict | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT * FROM database_connectors WHERE id = ?",
            (connector_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["config"] = json.loads(item.pop("config_json"))
    item["is_read_only"] = bool(item["is_read_only"])
    return item


def list_database_connectors() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM database_connectors ORDER BY updated_at DESC"
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["config"] = json.loads(item.pop("config_json"))
        item["is_read_only"] = bool(item["is_read_only"])
        results.append(item)
    return results


def delete_database_connector(connector_id: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM database_connectors WHERE id = ?",
            (connector_id,),
        )
    return cursor.rowcount > 0


# =========================================================================
# USER PREFERENCES & MEMORY DATA HELPERS
# =========================================================================

def get_user_preferences() -> dict[str, str]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT key, value FROM user_preferences"
        ).fetchall()
    return {row["key"]: row["value"] for row in rows}


def get_user_preference(key: str, default: str | None = None) -> str | None:
    with get_connection() as connection:
        row = connection.execute(
            "SELECT value FROM user_preferences WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else default


def set_user_preference(key: str, value: str, category: str = "general") -> None:
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO user_preferences (key, value, category, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key.strip(), value.strip(), category.strip()),
        )


def delete_user_preference(key: str) -> bool:
    with get_connection() as connection:
        cursor = connection.execute(
            "DELETE FROM user_preferences WHERE key = ?",
            (key,),
        )
    return cursor.rowcount > 0


def export_all_memory() -> dict:
    with get_connection() as connection:
        preferences = {
            row["key"]: row["value"]
            for row in connection.execute("SELECT key, value FROM user_preferences").fetchall()
        }
        workspace_contexts = [
            dict(row) for row in connection.execute("SELECT * FROM workspace_contexts").fetchall()
        ]
        documents = [
            {
                "title": row["title"],
                "file_path": row["file_path"],
                "chunk_count": row["chunk_count"],
                "size_bytes": row["size_bytes"],
            }
            for row in connection.execute("SELECT * FROM knowledge_documents").fetchall()
        ]
        connectors = [
            {
                "id": row["id"],
                "name": row["name"],
                "connector_type": row["connector_type"],
            }
            for row in connection.execute("SELECT id, name, connector_type FROM database_connectors").fetchall()
        ]

    return {
        "version": "1.0",
        "exported_at": str(Path(__file__).stat().st_mtime),
        "user_preferences": preferences,
        "workspace_contexts": workspace_contexts,
        "indexed_documents": documents,
        "database_connectors": connectors,
    }


def clear_all_memory() -> None:
    with get_connection() as connection:
        connection.execute("DELETE FROM user_preferences")
        connection.execute("DELETE FROM workspace_contexts")
