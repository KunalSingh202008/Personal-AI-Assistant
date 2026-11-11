from typing import Dict, Any, List, Optional
import action_policy
from workspace_tools import TOOL_SCHEMAS

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

    def get_tool_risk(self, action_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """
        Evaluate tool risk category (GREEN, AMBER, RED) using centralized action policy:
        - GREEN: Safe read-only inspection (auto-approved)
        - AMBER: Workspace writes and allowlisted commands (explicit user approval required)
        - RED: Destructive / unauthorized operations (strictly blocked)
        """
        try:
            policy = action_policy.classify_action(action_name)
            return policy.risk
        except Exception:
            return "RED"


tool_registry = ToolRegistry()
