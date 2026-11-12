"""
Unified Structured Intent Engine for KELA AI Platform.
Provides multi-tier intent classification, multilingual parsing (English, Hindi, Hinglish),
pronoun/entity awareness, and typed tool routing.
"""

import re
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple

from core.entity_tracker import entity_tracker
from core.tool_registry import tool_registry

logger = logging.getLogger("kela.intent_engine")

WAKE_WORDS = ["hey kela", "kela", "ok kela", "hello kela", "sun kela", "arrey kela", "oye kela"]

HINDI_INDICATORS = [
    "kholo", "chalao", "band karo", "badhao", "kam karo", "batao", "kya", "haal",
    "kaise", "samay", "kitna", "hai", "aaj", "lo", "kar do", "sun", "dhundo", "dhundho",
    "mera", "meri", "mere", "ise", "isko", "usko", "kaun", "hain", "karo", "dikhayo"
]

UNSUPPORTED_PATTERNS = [
    (r"\b(?:order|buy|purchase|book)\s+(?:a\s+)?(?:pizza|food|burger|coffee|flight|ticket|cab|uber|ola|groceries|item)\b", "ordering food, travel, or commercial purchases"),
    (r"\b(?:make|brew|prepare)\s+(?:me\s+)?(?:coffee|tea|dinner|lunch|breakfast)\b", "performing physical kitchen or real-world tasks"),
    (r"\b(?:wash|clean|iron)\s+(?:my\s+)?(?:clothes|car|room|dishes)\b", "performing physical chores"),
    (r"\b(?:drive|fly)\s+(?:a\s+)?(?:car|airplane|plane|drone)\b", "piloting physical vehicles"),
    (r"\b(?:hack|infiltrate|ddos|bypass security)\b", "unauthorized cyber activities or hacking"),
]


@dataclass
class IntentResult:
    intent_type: str  # "ACTION", "QUESTION", "CLARIFICATION_NEEDED", "UNSUPPORTED", "SESSION_CONTROL"
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    clarification_question: Optional[str] = None
    unsupported_reason: Optional[str] = None
    response_text: Optional[str] = None  # Direct response if fast-path
    confidence: float = 1.0
    language: str = "english"
    fast_path: bool = False
    stop_session: bool = False
    pause_session: bool = False
    is_followup: bool = False
    resolved_entity: Optional[Dict[str, Any]] = None


def is_wake_word_present(text: str) -> Tuple[bool, str]:
    """Check if 'Hey KELA' or wake word prefixes the query, stripping it if present."""
    clean = text.strip()
    lower = clean.lower()
    for ww in WAKE_WORDS:
        if lower.startswith(ww):
            stripped = clean[len(ww):].strip(" ,:!.-")
            return True, stripped
    return False, clean


def detect_language(text: str) -> str:
    """Detect if utterance is primarily Hindi/Hinglish or English."""
    lower = text.lower()
    matches = sum(1 for word in HINDI_INDICATORS if re.search(r'\b' + re.escape(word) + r'\b', lower))
    return "hinglish" if matches >= 1 else "english"


class IntentEngine:
    """
    Intelligent intent classification engine operating across 3 tiers:
    - Tier 0: Instant System Control & Session State (0ms)
    - Tier 1: Deterministic Semantic, Multilingual & Pronoun Resolution (<1ms)
    - Tier 2: LLM Structured Fallback for Complex Queries
    """

    def __init__(self):
        pass

    def classify_intent(
        self,
        raw_text: str,
        conversation_id: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> IntentResult:
        """
        Classifies user prompt into a structured IntentResult.
        """
        context = context or {}
        clean_text = raw_text.strip()
        _, stripped = is_wake_word_present(clean_text)
        query = stripped.strip() or clean_text
        lower = query.lower()
        lang = detect_language(lower)

        # -------------------------------------------------------------
        # Tier 0: Instant System Controls & Session State
        # -------------------------------------------------------------
        if not query:
            greeting = "Haan boliye Kunal, main sun raha hoon." if lang == "hinglish" else "Yes Kunal, I'm listening."
            return IntentResult(
                intent_type="SESSION_CONTROL",
                response_text=greeting,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(stop listening|stop session|bye kela|bye|so jao|exit voice|shut down voice)\b', lower):
            resp = "Alvida Kunal, voice session band kar raha hoon." if lang == "hinglish" else "Stopping listening. Call me whenever you need me, Kunal."
            return IntentResult(
                intent_type="SESSION_CONTROL",
                tool_name="stop_listening",
                response_text=resp,
                stop_session=True,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(pause listening|pause session|ruk jao|wait a minute)\b', lower):
            resp = "Voice listening pause kar di hai." if lang == "hinglish" else "Listening paused. Say resume or click the mic when you're ready."
            return IntentResult(
                intent_type="SESSION_CONTROL",
                tool_name="pause_listening",
                response_text=resp,
                pause_session=True,
                language=lang,
                fast_path=True,
            )

        # Assistant Identity
        if re.search(r'\b(who are you|what is your name|tum kaun ho|naam kya hai)\b', lower):
            resp = (
                "Main KELA hoon, aapka personal voice assistant aur AI operating system."
                if lang == "hinglish" else
                "I am KELA, your personal voice assistant and autonomous operating system."
            )
            return IntentResult(
                intent_type="QUESTION",
                tool_name="assistant_identity",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # User Identity
        if re.search(r'\b(who am i|mera naam kya hai|do you know me|who is kunal)\b', lower):
            resp = (
                "Aap Kunal Singh hain, B.Tech Computer Science ke student aur AI developer. Aap Nexus AI, StreeSure, aur ClassTrack AI par kaam kar rahe hain."
                if lang == "hinglish" else
                "You are Kunal Singh, a B.Tech Computer Science student and AI developer building Nexus AI, StreeSure, and ClassTrack AI."
            )
            return IntentResult(
                intent_type="QUESTION",
                tool_name="identity",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # Capabilities / Help
        if re.search(r'\b(what can you do|kya kar sakte ho|help me|features)\b', lower):
            resp = (
                "Main aapke apps launch kar sakta hoon, volume aur RAM status monitor kar sakta hoon, files aur projects search kar sakta hoon, aur coding tasks execute kar sakta hoon."
                if lang == "hinglish" else
                "I can launch your applications, manage system audio, monitor RAM and hardware status, find files and projects, and execute development tasks."
            )
            return IntentResult(
                intent_type="QUESTION",
                tool_name="help",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # My Projects
        if re.search(r'\b(my projects|tell me about my projects|current projects|mere projects)\b', lower):
            resp = (
                "Aapke core projects hain: Nexus AI, jo aapka autonomous personal AI operating system hai; StreeSure; aur ClassTrack AI."
                if lang == "hinglish" else
                "Your core projects are Nexus AI, your personal AI operating system, StreeSure for safety analytics, and ClassTrack AI for student workflows."
            )
            return IntentResult(
                intent_type="QUESTION",
                tool_name="projects_info",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # Greetings
        if re.search(r'^(?:hello|hi|hey|kya haal hai|kaise ho|how are you)$', lower) or (
            re.search(r'\b(hello|hi|hey|kya haal hai|kaise ho|how are you)\b', lower) and len(query.split()) <= 4
        ):
            resp = "Main badhiya hoon Kunal! Boliye, kis project ya task par kaam karein?" if lang == "hinglish" else "Hello Kunal! I am doing great. What would you like to work on next?"
            return IntentResult(
                intent_type="QUESTION",
                tool_name="greeting",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # -------------------------------------------------------------
        # Unsupported Operations Check (Never silently drop)
        # -------------------------------------------------------------
        for pat, reason in UNSUPPORTED_PATTERNS:
            if re.search(pat, lower):
                reason_msg = (
                    f"KELA {reason} ko execute nahi kar sakta. Main aapke PC controls, files, apps, aur development tasks manage kar sakta hoon."
                    if lang == "hinglish" else
                    f"I cannot assist with {reason}. I am designed to manage your PC, launch apps, search files, and execute development tasks."
                )
                return IntentResult(
                    intent_type="UNSUPPORTED",
                    unsupported_reason=reason,
                    response_text=reason_msg,
                    language=lang,
                    fast_path=True,
                )

        # -------------------------------------------------------------
        # Pronoun & Reference Resolution via Entity Tracker
        # -------------------------------------------------------------
        resolved_text, pronoun_meta = entity_tracker.resolve_pronouns(query, conversation_id)
        if pronoun_meta.get("resolved"):
            resolved_lower = resolved_text.lower()
            logger.info("Resolved pronoun '%s' -> '%s' (type: %s)", query, resolved_text, pronoun_meta.get("target_type"))

            # Resolved to project execution
            if pronoun_meta.get("target_type") == "project":
                proj = pronoun_meta["resolved_target"]
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="run_project",
                    parameters={"project_name": proj["name"], "project_path": proj.get("path")},
                    confidence=0.98,
                    language=lang,
                    resolved_entity=proj,
                )
            # Resolved to file open
            elif pronoun_meta.get("target_type") == "file":
                f = pronoun_meta["resolved_target"]
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="open_file_path",
                    parameters={"file_path": f["path"]},
                    confidence=0.98,
                    language=lang,
                    resolved_entity=f,
                )
            # Resolved to application launch
            elif pronoun_meta.get("target_type") == "app":
                app = pronoun_meta["resolved_target"]
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="launch_app",
                    parameters={"app_name": app},
                    confidence=0.98,
                    language=lang,
                )

        # -------------------------------------------------------------
        # Ambiguity Checks (When user uses bare pronouns with no context)
        # -------------------------------------------------------------
        if re.search(r'^(?:run it|start it|chalao ise|ise chalao|execute it)$', lower):
            cq = "Aap kis project ya application ko run karna chahte hain?" if lang == "hinglish" else "What project or application would you like me to run?"
            return IntentResult(
                intent_type="CLARIFICATION_NEEDED",
                clarification_question=cq,
                response_text=cq,
                language=lang,
                fast_path=True,
            )

        if re.search(r'^(?:open it|kholo ise|ise kholo|open the file|open that)$', lower):
            cq = "Aap kaun si file ya application kholna chahte hain?" if lang == "hinglish" else "Which file or application would you like me to open?"
            return IntentResult(
                intent_type="CLARIFICATION_NEEDED",
                clarification_question=cq,
                response_text=cq,
                language=lang,
                fast_path=True,
            )

        if re.search(r'^(?:delete it|delete that|ise delete karo|remove it)$', lower):
            cq = "Aap kis specific file ya directory ko delete karna chahte hain? Please specify the exact name." if lang == "hinglish" else "Which specific file or directory would you like to delete? Please specify the exact target."
            return IntentResult(
                intent_type="CLARIFICATION_NEEDED",
                clarification_question=cq,
                response_text=cq,
                language=lang,
                fast_path=True,
            )

        # -------------------------------------------------------------
        # Tier 1: Deterministic Semantic Patterns
        # -------------------------------------------------------------

        # Audio / Volume Controls
        if re.search(r'\b(volume up|increase volume|louder|awaz badhao|volume badhao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="change_volume",
                parameters={"direction": "up", "steps": 5},
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(volume down|decrease volume|softer|awaz kam karo|volume kam karo)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="change_volume",
                parameters={"direction": "down", "steps": 5},
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(mute|unmute|awaz band karo|chup ho jao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="toggle_mute",
                parameters={},
                language=lang,
                fast_path=True,
            )

        vol_match = re.search(r'(?:set volume to|volume)\s+(\d{1,3})\s*(?:percent|%)?', lower)
        if vol_match:
            target_val = int(vol_match.group(1))
            return IntentResult(
                intent_type="ACTION",
                tool_name="set_volume",
                parameters={"level": target_val},
                language=lang,
                fast_path=True,
            )

        # System Hardware & Telemetry
        if re.search(r'\b(ram usage|ram kitna|memory usage|what is my laptop\'?s? ram|pc ka ram|how much ram)\b', lower) or (
            re.search(r'\b(system metrics|system status|performance|pc ka haal|cpu usage)\b', lower)
        ):
            return IntentResult(
                intent_type="ACTION",
                tool_name="get_system_metrics",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(battery|charge|charging|battery kitni hai|battery status)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="get_system_metrics",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Disk Space & Storage Utilization
        if re.search(r'\b(free space|disk space|storage space|hard drive|free storage|space available|kitna space|space kitna|kitna storage|storage kitna|free disk|how much storage|storage left|storage remaining|storage available)\b', lower) or (
            re.search(r'\b(drive)\b', lower) and re.search(r'\b(free|space|capacity|most|storage)\b', lower)
        ) or (
            re.search(r'\b(storage|disk)\b', lower) and re.search(r'\b(how much|how many|kitna|left|remaining|available)\b', lower)
        ):
            target_drive = None
            d_match = re.search(r'\b([c-zC-Z])\s*(?:drive|:)\b', query)
            if d_match:
                target_drive = f"{d_match.group(1).upper()}:"
            return IntentResult(
                intent_type="ACTION",
                tool_name="get_disk_space",
                parameters={"drive": target_drive} if target_drive else {},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Running Processes & Top Memory Consumers
        if re.search(r'\b(processes|process list|running processes|apps consuming|consuming the most memory|consuming most memory|highest memory|top memory|kaun se processes|task manager list)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="list_running_processes",
                parameters={"limit": 10, "sort_by_memory": True},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Find Large Files
        if re.search(r'\b(large files|heavy files|badi files|biggest files|largest files|files taking space)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="find_large_files",
                parameters={"min_size_mb": 100, "max_results": 10},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Open Folder
        folder_open_match = re.search(r'\b(?:open|kholo)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\- ]+?)\s+folder\b', lower) or (
            re.search(r'\b(?:open|kholo)\s+(downloads|documents|desktop|videos|music|pictures)\b', lower)
        )
        if folder_open_match:
            folder_name = folder_open_match.group(1).strip()
            if folder_name in {"this", "the", "that"}:
                ctx = entity_tracker.get_context(conversation_id)
                if ctx.get("last_project"):
                    folder_name = ctx["last_project"].get("path") or ctx["last_project"].get("name")
                elif ctx.get("last_file"):
                    folder_name = ctx["last_file"].get("path", "")
            if folder_name:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="open_folder",
                    parameters={"folder_path": folder_name},
                    confidence=0.98,
                    language=lang,
                    fast_path=True,
                )

        # Previous Question / Reflection
        if re.search(r'\b(what did i ask|what was my last question|previous question|pichla sawal|pehle kya pucha)\b', lower):
            from core.conversation_manager import conversation_manager
            db_msgs = conversation_manager.get_messages(conversation_id) if conversation_id else []
            user_msgs = [m for m in db_msgs if m.get("role") == "user"]
            candidates = [
                m for m in user_msgs
                if not re.search(r'\b(what did i ask|last question|previous question|pichla sawal|pehle kya pucha)\b', m.get("content", "").lower())
            ]
            if candidates:
                last_q = candidates[-1]["content"]
                resp = f"Aapne pehle pucha tha: '{last_q}'" if lang == "hinglish" else f"You previously asked: '{last_q}'"
            else:
                resp = "Aapka koi pichla sawal nahi mila." if lang == "hinglish" else "I could not find any previous questions in this session."
            return IntentResult(
                intent_type="QUESTION",
                tool_name="reflection",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # Time & Date
        if re.search(r'\b(what time is it|current time|kya samay hua|time batao|kitne baje hain)\b', lower):
            import datetime
            now_str = datetime.datetime.now().strftime("%I:%M %p")
            resp = f"Abhi samay {now_str} hua hai." if lang == "hinglish" else f"It is currently {now_str}."
            return IntentResult(
                intent_type="QUESTION",
                tool_name="time",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(today\'?s? date|what is today|aaj ki date|aaj kaun sa din)\b', lower):
            import datetime
            date_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
            resp = f"Aaj ki tareekh {date_str} hai." if lang == "hinglish" else f"Today is {date_str}."
            return IntentResult(
                intent_type="QUESTION",
                tool_name="date",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # Desktop Screenshot
        if re.search(r'\b(take (?:a )?screenshot|capture screen|screen capture|screenshot lo|screenshot le lo)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="capture_desktop_screenshot",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Specific App Launchers: Calculator, Camera, etc.
        if re.search(r'\b(calculator|calc)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "calculator"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(camera|webcam)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "camera"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(chrome|google chrome|browser)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "chrome"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(vscode|vs code|code editor)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "vscode"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(notepad|editor)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "notepad"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        if re.search(r'\b(youtube)\b', lower) and re.search(r'\b(open|launch|play|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "youtube"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Generic Open / Launch Application
        open_app_match = re.search(
            r'\b(?:open|launch|start|kholo|chalao)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+)\b',
            lower
        )
        if open_app_match and not re.search(r'\b(?:website|link|page|url|tab|file|folder|resume|cv|pdf|project)\b', lower):
            app_raw = open_app_match.group(1).replace("kholo", "").replace("chalao", "").strip()
            # Clean common words
            for suffix in ["please", "for me", "app", "application"]:
                if app_raw.endswith(suffix):
                    app_raw = app_raw[:-len(suffix)].strip()
            if app_raw in {"calculator", "calc", "camera", "webcam", "chrome", "browser", "vscode", "vs code", "notepad", "spotify", "task manager", "paint", "explorer", "terminal"}:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="launch_app",
                    parameters={"app_name": app_raw},
                    confidence=0.95,
                    language=lang,
                    fast_path=True,
                )

        # Close Application
        close_match = re.search(r'\b(?:close|quit|exit|band karo)\s+(?:the\s+)?([a-zA-Z0-9_\- ]+)\b', lower)
        if close_match:
            app_raw = close_match.group(1).replace("band karo", "").strip()
            for suffix in ["please", "for me", "app", "application"]:
                if app_raw.endswith(suffix):
                    app_raw = app_raw[:-len(suffix)].strip()
            if app_raw in {"calculator", "calc", "camera", "webcam", "chrome", "browser", "vscode", "vs code", "notepad", "spotify", "task manager", "paint"}:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="close_app",
                    parameters={"app_name": app_raw},
                    confidence=0.95,
                    language=lang,
                    fast_path=True,
                )

        # Resume / CV Search
        if re.search(r'\b(find (?:my )?resume|where is (?:my )?resume|where did i save (?:my )?resume|resume dhundo|resume dhundho|open my resume|find (?:my )?cv|where is (?:my )?cv)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="find_resume_files",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Project Search (e.g. "Find my Phone Doctor project", "Where is Phone Doctor", "Phone Doctor project dhundo")
        if any(proj in lower for proj in ["phone doctor", "phonedoctor", "streesure", "classtrack"]):
            if any(term in lower for term in ["find", "where", "locate", "search", "dhundo", "dhundho", "kahan", "project"]):
                proj_name = "Phone Doctor" if ("phone doctor" in lower or "phonedoctor" in lower) else (
                    "StreeSure" if "streesure" in lower else "ClassTrack"
                )
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="search_user_files",
                    parameters={"query": proj_name},
                    confidence=0.98,
                    language=lang,
                    fast_path=True,
                )

        proj_search_match = re.search(
            r'\b(?:find|where is|locate|search for|dhundo|dhundho)\s+(?:my\s+)?([a-zA-Z0-9_\- ]+?)(?:\s+project|\s+folder)?(?:\.|\?|$)',
            lower
        )
        if proj_search_match:
            target_candidate = proj_search_match.group(1).strip()
            if target_candidate and target_candidate not in {"file", "it", "that", "this"}:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="search_user_files",
                    parameters={"query": target_candidate},
                    confidence=0.92,
                    language=lang,
                    fast_path=True,
                )

        # File & Folder Search
        if re.search(r'\b(search (?:my )?files for|find (?:my )?file|file dhundo)\s+([a-zA-Z0-9_\- ]+)\b', lower):
            file_match = re.search(r'\b(search (?:my )?files for|find (?:my )?file|file dhundo)\s+([a-zA-Z0-9_\- ]+)\b', lower)
            search_term = file_match.group(2).strip()
            return IntentResult(
                intent_type="ACTION",
                tool_name="search_user_files",
                parameters={"query": search_term},
                confidence=0.92,
                language=lang,
                fast_path=True,
            )

        # Web Search
        web_search_match = re.search(r'\b(?:search (?:the )?(?:internet|web) for|google|search for)\s+([a-zA-Z0-9_\- ]+)\b', lower)
        if web_search_match and not re.search(r'\b(?:file|folder|document|pdf|resume|cv|project)\b', lower):
            search_query = web_search_match.group(1).strip()
            return IntentResult(
                intent_type="ACTION",
                tool_name="web_search",
                parameters={"query": search_query},
                confidence=0.90,
                language=lang,
                fast_path=False,
            )

        # Follow-up conversational queries ("tell me more", "aur batao", "explain further")
        if re.search(r'^(?:tell me more|more details|explain further|aur batao|aur details do|what else)\b', lower):
            return IntentResult(
                intent_type="QUESTION",
                confidence=0.95,
                language=lang,
                is_followup=True,
            )

        # -------------------------------------------------------------
        # Tier 2: General Conversational Question
        # -------------------------------------------------------------
        return IntentResult(
            intent_type="QUESTION",
            confidence=0.85,
            language=lang,
        )

    def format_action_response(
        self,
        intent: IntentResult,
        result: Dict[str, Any],
        lang: str = "english",
    ) -> str:
        """
        Formats natural spoken/written responses from tool execution results
        in the user's detected language (English or Hinglish).
        """
        tool_name = intent.tool_name or ""
        params = intent.parameters
        status = result.get("status", "success")

        # 1. Application Launch
        if tool_name in {"launch_app", "launch_calculator", "launch_camera", "launch_notepad", "launch_chrome", "launch_vscode", "launch_youtube"}:
            app = params.get("app_name") or params.get("app") or tool_name.replace("launch_", "")
            app_display = app.capitalize()
            if status == "success":
                if lang == "hinglish":
                    return f"{app_display} khol diya hai."
                return f"Opening {app_display}."
            else:
                msg = result.get("message") or result.get("result", {}).get("message", "Application could not be launched.")
                if lang == "hinglish":
                    return f"{app_display} launch nahi ho saka: {msg}"
                return f"Failed to open {app_display}: {msg}"

        # 2. Application Close
        if tool_name == "close_app":
            app = params.get("app_name") or params.get("app", "Application")
            app_display = app.capitalize()
            if status == "success":
                if lang == "hinglish":
                    return f"{app_display} band kar diya hai."
                return f"Closed {app_display}."
            else:
                if lang == "hinglish":
                    return f"{app_display} band karne mein samasya aayi."
                return f"Could not close {app_display}."

        # 3. System Metrics / RAM
        if tool_name in {"get_system_metrics", "system_status"}:
            metrics = result.get("result", {}).get("metrics", {})
            ram_pct = metrics.get("ram_usage_percent", 50)
            used_mb = metrics.get("used_ram_mb", 8192)
            total_mb = metrics.get("total_ram_mb", 16384)
            used_gb = used_mb / 1024.0
            total_gb = total_mb / 1024.0
            battery_pct = metrics.get("battery_percent", 90)

            if lang == "hinglish":
                return f"Aapke laptop ka RAM usage {ram_pct}% hai ({used_gb:.1f} GB of {total_gb:.1f} GB used)."
            return f"Your laptop's RAM usage is currently {ram_pct}% ({used_gb:.1f} GB of {total_gb:.1f} GB used)."

        # 3b. Disk Space & Storage Utilization
        if tool_name == "get_disk_space":
            res_data = result.get("result", {})
            drives = res_data.get("drives", [])
            if not drives:
                msg = res_data.get("message", "Unable to read disk drives.")
                return f"Disk space information could not be retrieved: {msg}" if lang == "english" else f"Disk space ki jankari nahi mil saki: {msg}"

            parts_en = []
            parts_hi = []
            for d in drives:
                d_name = d.get("drive", "")
                free_gb = d.get("free_gb", 0)
                tot_gb = d.get("total_gb", 0)
                used_pct = d.get("used_percent", 0)
                parts_en.append(f"{d_name} has {free_gb} GB free out of {tot_gb} GB ({used_pct}% used)")
                parts_hi.append(f"{d_name} mein {free_gb} GB free hai {tot_gb} GB mein se ({used_pct}% used)")

            summary_str_en = ". ".join(parts_en) + "."
            summary_str_hi = ". ".join(parts_hi) + "."

            if len(drives) > 1:
                most_free = res_data.get("most_free_drive")
                most_gb = res_data.get("most_free_gb")
                if most_free and most_gb:
                    summary_str_en += f" Drive with the most free space is {most_free} with {most_gb} GB available."
                    summary_str_hi += f" Sabse zyada free space {most_free} drive mein hai ({most_gb} GB available)."

            return summary_str_hi if lang == "hinglish" else summary_str_en

        # 3c. Running Processes & Memory
        if tool_name == "list_running_processes":
            res_data = result.get("result", {})
            procs = res_data.get("processes", [])
            if not procs:
                return "No running processes found." if lang == "english" else "Koi running process nahi mila."

            top_3 = procs[:3]
            proc_desc_en = ", ".join([f"{p.get('ProcessName')} ({p.get('MemoryMB')} MB)" for p in top_3])
            proc_desc_hi = ", ".join([f"{p.get('ProcessName')} ({p.get('MemoryMB')} MB)" for p in top_3])

            if lang == "hinglish":
                return f"Sabse zyada memory lene wale top processes hain: {proc_desc_hi}. Total {res_data.get('total_unique_processes', len(procs))} unique processes active hain."
            return f"Top memory-consuming processes are: {proc_desc_en}. There are {res_data.get('total_unique_processes', len(procs))} unique processes currently active."

        # 3d. Large Files Search
        if tool_name == "find_large_files":
            res_data = result.get("result", {})
            files = res_data.get("files", [])
            min_mb = res_data.get("min_size_mb", 100)
            if not files:
                if lang == "hinglish":
                    return f"Aapke user folders mein {min_mb} MB se badi koi file nahi mili."
                return f"No files larger than {min_mb} MB were found in your user directories."

            top_files = files[:3]
            f_parts_en = [f"'{f.get('name')}' ({f.get('size_mb')} MB in {f.get('folder')})" for f in top_files]
            f_parts_hi = [f"'{f.get('name')}' ({f.get('size_mb')} MB, {f.get('folder')})" for f in top_files]

            if lang == "hinglish":
                return f"Maine {len(files)} badi files dhundi hain: {', '.join(f_parts_hi)}."
            return f"Found {len(files)} large files taking the most space: {', '.join(f_parts_en)}."

        # 3e. Open Folder
        if tool_name == "open_folder":
            res_data = result.get("result", {})
            f_path = res_data.get("path") or params.get("folder_path", "")
            if status == "success" or res_data.get("status") == "success":
                if lang == "hinglish":
                    return f"Folder khol diya hai: {f_path}"
                return f"Opened folder: {f_path}"
            else:
                msg = res_data.get("message", "Unable to open folder.")
                if lang == "hinglish":
                    return f"Folder nahi khul saka: {msg}"
                return f"Failed to open folder: {msg}"

        # 4. Resume Search
        if tool_name in {"find_resume_files", "find_resume"}:
            items = result.get("result", {}).get("results", [])
            if items:
                first = items[0]
                path = first.get("path", "")
                if lang == "hinglish":
                    return f"Aapka resume mil gaya: {path}"
                return f"Found your resume at {path}."
            else:
                if lang == "hinglish":
                    return "Maine aapke Downloads, Documents, aur Desktop folders mein check kiya, par koi resume ya CV nahi mila."
                return "I searched your Downloads, Documents, and Desktop folders, but could not find any resume or CV files."

        # 5. File / Project Search
        if tool_name == "search_user_files":
            q = params.get("query", "")
            items = result.get("result", {}).get("results", [])
            if items:
                # Check for project directory
                projects = [it for it in items if it.get("is_project") or it.get("type") == "directory"]
                if projects:
                    proj = projects[0]
                    pname = proj.get("name", q)
                    ppath = proj.get("path", "")
                    if lang == "hinglish":
                        return f"{pname} project {proj.get('folder', 'system')} mein mil gaya: {ppath}"
                    return f"Found your {pname} project at {ppath}."
                else:
                    first = items[0]
                    fname = first.get("name", "")
                    fpath = first.get("path", "")
                    if lang == "hinglish":
                        return f"'{fname}' file mil gayi hai: {fpath}"
                    return f"Found '{fname}' at {fpath}."
            else:
                if lang == "hinglish":
                    return f"Downloads, Documents, aur Desktop mein '{q}' nahi mila."
                return f"Could not find any files or projects matching '{q}' in your user folders."

        # 6. Run Project
        if tool_name == "run_project":
            pname = params.get("project_name") or result.get("project_name", "project")
            if result.get("requires_approval"):
                if lang == "hinglish":
                    return f"{pname} project locally run karne ke liye approval zaroori hai. Kripya approve karein."
                return f"Running project '{pname}' requires execution approval."
            return f"Started project {pname}."

        # 7. Volume Adjustments
        if tool_name == "change_volume":
            direction = params.get("direction", "up")
            if lang == "hinglish":
                return "Volume badha diya hai." if direction == "up" else "Volume kam kar diya hai."
            return f"Volume {direction} adjusted."

        if tool_name == "set_volume":
            lvl = params.get("level", 50)
            if lang == "hinglish":
                return f"Volume {lvl} percent par set kar diya."
            return f"Volume set to {lvl}%."

        if tool_name == "toggle_mute":
            if lang == "hinglish":
                return "Audio mute toggle kar diya."
            return "Audio mute toggled."

        # 8. Screenshot
        if tool_name in {"capture_desktop_screenshot", "screenshot"}:
            if lang == "hinglish":
                return "Desktop screenshot capture kar liya hai."
            return "Desktop screenshot captured."

        # Fallback
        return "Task completed successfully." if lang == "english" else "Operation poora ho gaya hai."


intent_engine = IntentEngine()
