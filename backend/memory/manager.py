from typing import Any
from database import (
    clear_all_memory,
    delete_user_preference,
    export_all_memory,
    get_user_preference,
    get_user_preferences,
    get_workspace_context,
    set_user_preference,
    set_workspace_context,
)


class MemoryManager:
    """
    Orchestrates strictly separated memory layers:
    1. Conversation History (Conversations/Messages)
    2. Persistent Preferences (User Profile, Persona, Style)
    3. Workspace Context (Current selected project guidelines)
    4. Retrieved Knowledge (Index Chunks / Documents)
    5. Agent Task State (Ephemeral execution progress)
    """

    @classmethod
    def get_preferences(cls) -> dict[str, str]:
        return get_user_preferences()

    @classmethod
    def set_preference(cls, key: str, value: str, category: str = "general") -> None:
        set_user_preference(key, value, category)

    @classmethod
    def remove_preference(cls, key: str) -> bool:
        return delete_user_preference(key)

    @classmethod
    def get_workspace_knowledge(cls, workspace_path: str) -> str:
        return get_workspace_context(workspace_path)

    @classmethod
    def set_workspace_knowledge(cls, workspace_path: str, context: str) -> None:
        set_workspace_context(workspace_path, context)

    @classmethod
    def export_snapshot(cls) -> dict:
        return export_all_memory()

    @classmethod
    def clear_memory(cls) -> None:
        clear_all_memory()

    @classmethod
    def build_context_injection(cls, workspace_path: str | None = None) -> str:
        parts = []

        prefs = get_user_preferences()
        if prefs:
            pref_lines = [f"- {k}: {v}" for k, v in prefs.items()]
            parts.append(
                "[PERSISTENT USER PREFERENCES]\n"
                "The user has defined the following persistent preferences for your responses:\n"
                + "\n".join(pref_lines)
            )

        if workspace_path:
            ws_ctx = get_workspace_context(workspace_path)
            if ws_ctx:
                parts.append(
                    "[PROJECT WORKSPACE CONTEXT]\n"
                    f"Saved architectural guidelines and conventions for this workspace:\n{ws_ctx}"
                )

        return "\n\n".join(parts)
