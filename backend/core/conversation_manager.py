import logging
import threading
from typing import Dict, Any, List, Optional
import database

logger = logging.getLogger("kela.conversation")

class ConversationManager:
    """
    Manages persistent conversation sessions, message history,
    idempotent turn generation, and concurrency locks to prevent race conditions.
    """

    def __init__(self):
        self._active_turn_locks: set[str] = set()
        self._lock = threading.Lock()

    def acquire_turn_lock(self, conversation_id: int, turn_id: str) -> bool:
        """Prevent concurrent duplicate execution of the exact same conversation turn."""
        key = f"{conversation_id}:{turn_id}"
        with self._lock:
            if key in self._active_turn_locks:
                return False
            self._active_turn_locks.add(key)
            return True

    def release_turn_lock(self, conversation_id: int, turn_id: str):
        """Release the active turn lock upon turn completion or cancellation."""
        key = f"{conversation_id}:{turn_id}"
        with self._lock:
            self._active_turn_locks.discard(key)

    def create_conversation(self, title: str = "New chat") -> Dict[str, Any]:
        """Create a new conversation session and return its stable ID and metadata."""
        return database.create_conversation(title=title)

    def get_conversation(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        """Fetch conversation metadata by ID."""
        conv = database.get_conversation_by_id(conversation_id)
        if not conv:
            return None
        return dict(conv)

    def list_conversations(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List past conversations ordered by updated_at descending."""
        return [dict(c) for c in database.list_conversations()[:limit]]

    def rename_conversation(self, conversation_id: int, title: str) -> bool:
        """Rename an existing conversation."""
        clean_title = title.strip()
        if not clean_title:
            return False
        with database.get_connection() as connection:
            cursor = connection.execute(
                "UPDATE conversations SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (clean_title, conversation_id),
            )
            return cursor.rowcount > 0

    def delete_conversation(self, conversation_id: int) -> bool:
        """Delete conversation and all its cascaded messages."""
        with database.get_connection() as connection:
            connection.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cursor = connection.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            return cursor.rowcount > 0

    def get_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """Retrieve all stored messages for a conversation in chronological order."""
        with database.get_connection() as connection:
            rows = connection.execute(
                "SELECT id, role, content, client_message_id, created_at FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_user_message(
        self,
        conversation_id: int,
        content: str,
        client_message_id: Optional[str] = None,
    ) -> int:
        """Persist user message with optional idempotency key."""
        return database.save_message(
            conversation_id=conversation_id,
            role="user",
            content=content,
            client_message_id=client_message_id,
        )

    def save_assistant_message(
        self,
        conversation_id: int,
        content: str,
        client_message_id: Optional[str] = None,
    ) -> int:
        """
        Persist completed assistant response.
        Incomplete/empty responses are rejected to preserve data integrity.
        """
        clean = content.strip()
        if not clean:
            return 0
        return database.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=clean,
            client_message_id=client_message_id,
        )


conversation_manager = ConversationManager()
