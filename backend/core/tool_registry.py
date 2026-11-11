from typing import Dict, Any, List, Optional
import action_policy
from workspace_tools import TOOL_SCHEMAS

SAFE_VOICE_ACTIONS = {
    # System & Audio
    "volume_up", "volume_down", "set_volume", "toggle_mute",
    # Native Apps & Tools
    "launch_camera", "launch_youtube", "launch_chrome", "launch_vscode",
    "launch_calculator", "launch_notepad", "launch_app", "close_app",
    # File & Status
    "find_resume", "open_latest_pdf", "open_downloads",
    "screenshot", "battery_status", "system_status", "time", "date",
    "web_search", "web_search_summary",
    # Conversational / Assistant State
    "stop_listening", "pause_listening", "assistant_identity",
    "help", "identity", "projects_info", "greeting", "conversational_ai"
}

class ToolRegistry:
    """
    Centralized tool registry managing tool schemas, action risk levels,
    and invocation boundaries across the KELA AI platform.
    """

    def __init__(self):
        self._schemas = {schema["name"]: schema for schema in TOOL_SCHEMAS}

    def list_schemas(self) -> List[Dict[str, Any]]:
        """Return registered JSON schemas for all available tools."""
        return list(self._schemas.values())

    def get_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """Retrieve schema for specific tool by name."""
        return self._schemas.get(tool_name)

    def is_safe_voice_action(self, action_name: str) -> bool:
        """Check whether action is allowlisted for voice execution."""
        return action_name in SAFE_VOICE_ACTIONS

    def get_tool_risk(self, action_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Evaluate tool risk category (GREEN, AMBER, RED) using centralized action policy:
        - GREEN: Safe read-only inspection or allowlisted voice action (auto-approved)
        - AMBER: Workspace writes and allowlisted commands (explicit user approval required)
        - RED: Destructive / unauthorized operations (strictly blocked)
        """
        if action_name in SAFE_VOICE_ACTIONS:
            return "GREEN"
        try:
            policy = action_policy.classify_action(action_name)
            return policy.risk
        except Exception:
            return "RED"


tool_registry = ToolRegistry()

