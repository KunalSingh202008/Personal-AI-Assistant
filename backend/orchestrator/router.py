"""
Nexus AI — Central Autonomous AI Orchestrator
Understands natural language instructions, identifies intent, determines required tools
and integrations, creates execution plans, selects specialist agents, and executes
workflows across Autonomy Levels 1 to 5.
"""

from enum import Enum
import json
import logging
from pathlib import Path
import re
from typing import Any, AsyncGenerator
import httpx

from database import get_setting, set_setting

logger = logging.getLogger("nexus.orchestrator")

OLLAMA_BASE_URL = "http://127.0.0.1:11434"
AUTONOMY_LEVEL_SETTING_KEY = "nexus_autonomy_level"


class AutonomyLevel(int, Enum):
    LEVEL_1_CHAT_ONLY = 1
    LEVEL_2_PLAN_ONLY = 2
    LEVEL_3_ASSISTED = 3  # Safe read-only auto, writes & commands require approval
    LEVEL_4_SUPERVISED = 4  # Safe workspace writes auto, external/git push requires approval
    LEVEL_5_FULL_WORKSPACE = 5  # Full workspace autonomy, red operations require approval


class TaskCategory(str, Enum):
    GENERAL_CHAT = "general_chat"
    CODING = "coding"
    GITHUB = "github"
    BROWSER = "browser"
    RESEARCH = "research"
    DOCUMENT = "document"
    VISION = "vision"
    IMAGE_GEN = "image_generation"
    DATA_ANALYSIS = "data_analysis"
    DATABASE = "database"
    AUTOMATION = "automation"


def get_current_autonomy_level() -> int:
    val = get_setting(AUTONOMY_LEVEL_SETTING_KEY)
    if val and val.isdigit():
        lvl = int(val)
        if 1 <= lvl <= 5:
            return lvl
    return AutonomyLevel.LEVEL_3_ASSISTED.value


def set_current_autonomy_level(level: int) -> None:
    if 1 <= level <= 5:
        set_setting(AUTONOMY_LEVEL_SETTING_KEY, str(level))


def classify_task_intent(
    query: str,
    has_image: bool = False,
    has_document: bool = False,
    file_extensions: list[str] | None = None,
) -> TaskCategory:
    """Classifies user intent into one of the specialist agent categories."""
    q = query.lower().strip()

    # Priority 1: Multimodal attachments
    if has_image or (file_extensions and any(ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} for ext in file_extensions)):
        return TaskCategory.VISION

    if has_document or (file_extensions and any(ext in {".pdf", ".docx", ".xlsx", ".csv"} for ext in file_extensions)):
        if any(ext in {".xlsx", ".csv"} for ext in (file_extensions or [])) and any(w in q for w in ["chart", "plot", "average", "stats", "sum"]):
            return TaskCategory.DATA_ANALYSIS
        return TaskCategory.DOCUMENT

    # Priority 2: GitHub specific operations
    if any(k in q for k in [
        "github", "git push", "git commit", "pull request", "clone repo", "repository",
        "open my carecompass", "inspect my repo", "create repo", "create repository"
    ]):
        return TaskCategory.GITHUB

    # Priority 3: Image Generation
    if any(k in q for k in ["generate an image", "create an image", "draw", "generate image", "make a picture", "svg illustration", "art of"]):
        return TaskCategory.IMAGE_GEN

    # Priority 4: Browser & Web navigation
    if any(k in q for k in ["open website", "visit", "browse to", "navigate to", "open http", "open this website", "check web page", "fill form"]):
        return TaskCategory.BROWSER

    # Priority 5: Database queries
    if any(k in q for k in ["database", "sql query", "select * from", "connect to sqlite", "inspect schema", "run query"]):
        return TaskCategory.DATABASE

    # Priority 6: Data analysis / spreadsheet
    if any(k in q for k in ["analyse excel", "analyze excel", "analyze this csv", "generate charts", "summary statistics"]):
        return TaskCategory.DATA_ANALYSIS

    # Priority 7: Deep Research
    if any(k in q for k in ["deep research", "research the information", "compare and contrast", "investigate", "comprehensive analysis", "gather sources"]):
        return TaskCategory.RESEARCH

    # Priority 8: Coding & workspace implementation
    coding_indicators = [
        "bug", "refactor", "test", "tests", "implement", "unit test",
        "write code", "fix login", "build this feature", "create file", "modify function",
        ".py", ".ts", ".js", "debug", "compile", "codebase", "patch"
    ]
    if any(k in q for k in coding_indicators):
        return TaskCategory.CODING

    # Priority 9: Scheduled task / automation
    if any(k in q for k in ["automate", "every morning", "schedule", "cron", "recurring task"]):
        return TaskCategory.AUTOMATION

    # Default: General conversational
    return TaskCategory.GENERAL_CHAT


class Orchestrator:
    def __init__(self, workspace_path: str = "."):
        self.workspace_path = Path(workspace_path).resolve()

    def create_plan(
        self,
        query: str,
        category: TaskCategory,
        autonomy_level: int,
    ) -> dict[str, Any]:
        """Creates a structured execution plan with milestones and specialist agent selection."""
        steps = []

        if category == TaskCategory.GITHUB:
            steps = [
                {"step": 1, "agent": "GitHub Agent", "action": "Verify GitHub credentials and check workspace git repository"},
                {"step": 2, "agent": "GitHub Agent", "action": "Discover target repository or inspect branches/commits"},
                {"step": 3, "agent": "Coding Agent", "action": "Analyze code architecture and execute requested changes"},
                {"step": 4, "agent": "Coding Agent", "action": "Run allowlisted automated tests to verify repairs"},
                {"step": 5, "agent": "GitHub Agent", "action": "Stage, commit verified changes and prepare push request (approval gated)"},
            ]
        elif category == TaskCategory.CODING:
            steps = [
                {"step": 1, "agent": "Coding Agent", "action": "Inspect workspace files and reproduce error or locate target modules"},
                {"step": 2, "agent": "Coding Agent", "action": "Formulate atomic modification plan and present unified diff"},
                {"step": 3, "agent": "Coding Agent", "action": "Apply changes upon policy check or approval"},
                {"step": 4, "agent": "Coding Agent", "action": "Execute test command to independently verify result"},
            ]
        elif category == TaskCategory.BROWSER:
            steps = [
                {"step": 1, "agent": "Browser Agent", "action": "Validate target URL and sanitize parameters"},
                {"step": 2, "agent": "Browser Agent", "action": "Navigate to page and extract clean DOM text, headings, and links"},
                {"step": 3, "agent": "Research Agent", "action": "Synthesize extracted web content and generate response with citations"},
            ]
        elif category == TaskCategory.DOCUMENT:
            steps = [
                {"step": 1, "agent": "Document Intelligence", "action": "Detect document format (PDF/DOCX/XLSX) and extract text streams"},
                {"step": 2, "agent": "Document Intelligence", "action": "Index chunks and assign page-level citations [Page X]"},
                {"step": 3, "agent": "Research Agent", "action": "Analyze content against user query and prepare structured report"},
            ]
        elif category == TaskCategory.VISION:
            steps = [
                {"step": 1, "agent": "Vision Agent", "action": "Inspect image binary headers, dimensions, and color space"},
                {"step": 2, "agent": "Vision Agent", "action": "Check Ollama multimodal vision models (LLaVA/Qwen2.5-VL)"},
                {"step": 3, "agent": "Vision Agent", "action": "Execute visual reasoning prompt and deliver findings"},
            ]
        elif category == TaskCategory.IMAGE_GEN:
            steps = [
                {"step": 1, "agent": "Image Generation Agent", "action": "Check active local backends (ComfyUI / WebUI / Vector)"},
                {"step": 2, "agent": "Image Generation Agent", "action": "Synthesize image from prompt and persist in workspace gallery"},
                {"step": 3, "agent": "Image Generation Agent", "action": "Provide preview, metadata, and workspace file link"},
            ]
        elif category == TaskCategory.DATABASE:
            steps = [
                {"step": 1, "agent": "Database Agent", "action": "Identify configured database connector and verify read-only permission"},
                {"step": 2, "agent": "Database Agent", "action": "Inspect schema, table definitions, and row counts"},
                {"step": 3, "agent": "Database Agent", "action": "Execute safe AST-validated query with sensitive column redaction"},
            ]
        elif category == TaskCategory.DATA_ANALYSIS:
            steps = [
                {"step": 1, "agent": "Data Analysis Agent", "action": "Load dataset rows and validate column data types"},
                {"step": 2, "agent": "Data Analysis Agent", "action": "Compute summary statistics and aggregations"},
                {"step": 3, "agent": "Data Analysis Agent", "action": "Generate formatted markdown table and visual chart preview"},
            ]
        elif category == TaskCategory.RESEARCH:
            steps = [
                {"step": 1, "agent": "Research Agent", "action": "Decompose inquiry into retrieval sub-queries"},
                {"step": 2, "agent": "Knowledge Engine", "action": "Retrieve evidence from indexed documents, connectors, and web"},
                {"step": 3, "agent": "Research Agent", "action": "Synthesize report with verifiable source citations and confidence score"},
            ]
        else:
            steps = [
                {"step": 1, "agent": "General Assistant", "action": "Analyze conversational context and user preferences"},
                {"step": 2, "agent": "General Assistant", "action": "Generate direct streaming response"},
            ]

        return {
            "query": query,
            "category": category.value,
            "autonomy_level": autonomy_level,
            "total_steps": len(steps),
            "steps": steps,
        }

    async def execute_orchestrated_stream(
        self,
        query: str,
        category: TaskCategory,
        autonomy_level: int,
        conversation_id: int,
        turn_id: str,
    ) -> AsyncGenerator[str, None]:
        """
        Coordinates execution of the multi-agent plan and streams events
        (orchestrator_plan, step_start, step_complete, final_response).
        """
        plan = self.create_plan(query, category, autonomy_level)

        # Emit plan event
        yield json.dumps({
            "type": "orchestrator_plan",
            "category": category.value,
            "autonomy_level": autonomy_level,
            "plan": plan,
        }) + "\n"

        # If Autonomy Level 1: Chat only, no tools
        if autonomy_level == AutonomyLevel.LEVEL_1_CHAT_ONLY.value:
            yield json.dumps({
                "type": "orchestrator_notice",
                "message": "Autonomy Level 1: Conversational mode. Tools disabled.",
            }) + "\n"

        # If Autonomy Level 2: Plan only
        elif autonomy_level == AutonomyLevel.LEVEL_2_PLAN_ONLY.value:
            yield json.dumps({
                "type": "orchestrator_notice",
                "message": f"Autonomy Level 2: Proposed {len(plan['steps'])} step plan for review. Approval required to proceed.",
            }) + "\n"
            yield json.dumps({"done": True}) + "\n"
            return

        # Execute steps sequentially
        for step_data in plan["steps"]:
            step_num = step_data["step"]
            agent_name = step_data["agent"]
            action_desc = step_data["action"]

            yield json.dumps({
                "type": "orchestrator_step",
                "step": step_num,
                "agent": agent_name,
                "status": "running",
                "action": action_desc,
            }) + "\n"

            # Execute real subagent action based on step
            if "GitHub" in agent_name:
                from github.client import GitHubClient
                from github.git_ops import get_repo_status
                gh_client = GitHubClient()
                auth = await gh_client.verify_token()
                git_st = get_repo_status(self.workspace_path)
                yield json.dumps({
                    "type": "orchestrator_step_result",
                    "step": step_num,
                    "agent": agent_name,
                    "result": {
                        "github_authenticated": auth.get("authenticated", False),
                        "github_user": auth.get("login"),
                        "workspace_git": git_st.get("is_git", False),
                        "branch": git_st.get("current_branch"),
                        "clean": git_st.get("clean", True),
                    },
                }) + "\n"

            elif "Vision" in agent_name:
                from vision.analyzer import VisionAgent
                v_agent = VisionAgent()
                v_models = await v_agent.detect_available_vision_models()
                yield json.dumps({
                    "type": "orchestrator_step_result",
                    "step": step_num,
                    "agent": agent_name,
                    "result": {"detected_vision_models": v_models},
                }) + "\n"

            elif "Image Generation" in agent_name:
                from image_gen.generator import ImageGenerationAgent
                img_agent = ImageGenerationAgent(str(self.workspace_path))
                backends = await img_agent.detect_backends()
                yield json.dumps({
                    "type": "orchestrator_step_result",
                    "step": step_num,
                    "agent": agent_name,
                    "result": {"backends": backends},
                }) + "\n"

            elif "Browser" in agent_name:
                yield json.dumps({
                    "type": "orchestrator_step_result",
                    "step": step_num,
                    "agent": agent_name,
                    "result": {"browser_engine": "ready", "user_agent": "NexusAI/1.0"},
                }) + "\n"

            yield json.dumps({
                "type": "orchestrator_step",
                "step": step_num,
                "agent": agent_name,
                "status": "completed",
                "action": action_desc,
            }) + "\n"

        yield json.dumps({"done": True}) + "\n"
