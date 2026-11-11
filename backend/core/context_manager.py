import logging
from typing import Dict, Any, List, Optional
import database
from memory.manager import MemoryManager

logger = logging.getLogger("kela.context")

DEFAULT_MAX_CONTEXT_CHARS = 24000  # ~6,000 tokens safe context bound
MAX_PROJECT_CONTEXT_CHARS = 8000

class ContextManager:
    """
    Manages context window budgeting, history pruning, and persistent preferences.
    Guarantees the model context never overflows or crashes local inference.
    """

    def __init__(self, max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS):
        self.max_context_chars = max_context_chars

    def get_workspace_context(self, workspace_path: str) -> str:
        """Fetch workspace project context bounded to max 8,000 chars."""
        raw = database.get_workspace_context(workspace_path)
        return raw[:MAX_PROJECT_CONTEXT_CHARS] if raw else ""

    def get_user_preferences_block(self) -> Optional[str]:
        """Fetch stored user preferences and format as structured system context."""
        prefs = MemoryManager.get_preferences()
        if not prefs:
            return None
        lines = [f"- {k}: {v}" for k, v in prefs.items()]
        return "User persistent preferences for responses:\n" + "\n".join(lines)

    def prune_conversation_history(
        self,
        messages: List[Dict[str, Any]],
        max_chars: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Prunes message history to stay strictly within character/token budget:
        1. Always preserves the first system instruction message.
        2. Always preserves the latest user query.
        3. Retains most recent conversational turns, dropping oldest intermediate turns first.
        """
        budget = max_chars or self.max_context_chars
        if not messages:
            return []

        total_len = sum(len(m.get("content", "")) for m in messages)
        if total_len <= budget:
            return messages

        # Separate system messages, history, and the final prompt
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]

        if not non_system:
            return system_msgs

        final_msg = non_system[-1]
        intermediate = non_system[:-1]

        preserved_len = sum(len(m.get("content", "")) for m in system_msgs) + len(final_msg.get("content", ""))
        available = budget - preserved_len

        # Keep as many recent intermediate messages as possible
        kept_intermediate = []
        for msg in reversed(intermediate):
            msg_len = len(msg.get("content", ""))
            if available - msg_len >= 0:
                kept_intermediate.insert(0, msg)
                available -= msg_len
            else:
                break

        pruned = system_msgs + kept_intermediate + [final_msg]
        logger.info(
            "Context pruned: original %d messages (%d chars) -> kept %d messages (%d chars)",
            len(messages),
            total_len,
            len(pruned),
            sum(len(m.get("content", "")) for m in pruned),
        )
        return pruned


context_manager = ContextManager()
