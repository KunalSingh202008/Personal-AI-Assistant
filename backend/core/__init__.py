"""
KELA Core Intelligence Engine Package
Modular architecture separating conversation management, provider routing,
context budgeting, prompt assembly, and local security.
"""

from .provider_manager import (
    BaseInferenceProvider,
    OllamaProvider,
    CloudProviderAdapter,
    ProviderManager,
)
from .permission_manager import (
    PermissionManager,
    require_local_auth,
    get_or_create_local_token,
)
from .context_manager import ContextManager
from .prompt_manager import PromptManager
from .conversation_manager import ConversationManager
from .tool_registry import ToolRegistry
from .engine import KelaEngine

__all__ = [
    "BaseInferenceProvider",
    "OllamaProvider",
    "CloudProviderAdapter",
    "ProviderManager",
    "PermissionManager",
    "require_local_auth",
    "get_or_create_local_token",
    "ContextManager",
    "PromptManager",
    "ConversationManager",
    "ToolRegistry",
    "KelaEngine",
]
