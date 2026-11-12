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

            # Resolved to project execution or opening
            if pronoun_meta.get("target_type") == "project":
                proj = pronoun_meta["resolved_target"]
                if "analyse project" in resolved_lower or "analyze project" in resolved_lower:
                    return IntentResult(
                        intent_type="ACTION",
                        tool_name="analyze_project_folder",
                        parameters={"project_path_or_name": proj.get("path") or proj.get("name")},
                        confidence=0.98,
                        language=lang,
                        resolved_entity=proj,
                        fast_path=True,
                    )
                if "open folder" in resolved_lower or "open" in lower or "kholo" in lower:
                    return IntentResult(
                        intent_type="ACTION",
                        tool_name="open_folder",
                        parameters={"folder_path": proj.get("path")},
                        confidence=0.98,
                        language=lang,
                        resolved_entity=proj,
                        fast_path=True,
                    )
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
        # Conversational Follow-up Check
        # -------------------------------------------------------------
        ctx = entity_tracker.get_context(conversation_id) if conversation_id else {}
        from pc_control.task_planner import task_planner
        followup_res = task_planner.handle_followup(query, ctx, lang=lang)
        if followup_res and followup_res.get("handled"):
            if followup_res.get("selected_entity"):
                entity_tracker.update_context(
                    conversation_id,
                    last_file=followup_res.get("selected_entity") if followup_res.get("entity_type") == "file" else None,
                    last_entity_type=followup_res.get("entity_type", "file"),
                )
            return IntentResult(
                intent_type="QUESTION",
                tool_name="followup",
                response_text=followup_res["response_text"],
                language=lang,
                fast_path=True,
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

        # File Deletion / Safe Recycle (Safely Classified as RED risk by ToolRegistry)
        if not re.search(r'\b(which|what|can i|kaun|kya|batao|how)\b', lower):
            del_match = re.search(r'\b(?:delete|remove|recycle|hatao|mitao)\s+(?:file|the file)\s+["\']?([^"\']+)["\']?', query, re.IGNORECASE)
            if not del_match:
                del_match = re.search(r'^(?:please\s+|kripya\s+)?(?:delete|remove|recycle)\s+["\']?([a-zA-Z0-9_\-\.\\\/: ]+\.[a-zA-Z0-9_]+)["\']?', query, re.IGNORECASE)
            if del_match:
                target_del = del_match.group(1).strip()
                if target_del.lower() not in {"it", "that", "ise", "usko", "this", "my", "the"}:
                    return IntentResult(
                        intent_type="ACTION",
                        tool_name="recycle_file_safely",
                        parameters={"file_path": target_del, "target_path": target_del},
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

        # System Hardware, RAM & Telemetry
        if (
            re.search(r'\b(ram|memory)\b', lower) and re.search(r'\b(use|using|used|kitni|kitna|usage|free|available|consumption|status|batao|check)\b', lower)
        ) or re.search(r'\b(ram usage|ram kitna|ram kitni|memory usage|what is my laptop\'?s? ram|pc ka ram|how much ram|laptop ki ram)\b', lower) or (
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

        # Which drive is almost full?
        if re.search(r'\b(which drives?|kaun sa drive|kaun se drives?|which partitions?|konsa drive)\b', lower) and re.search(r'\b(full|almost full|bhar gaya|bhari|space kam)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="get_disk_space",
                parameters={"almost_full_only": True},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Multi-step Slowness & Performance Diagnostic
        if (
            re.search(r'\b(slow|lag|hang|atatak|bottleneck|performance issue|kyu chal raha hai|suggest improvements)\b', lower)
            and re.search(r'\b(laptop|pc|computer|system|check|analyse|analyze|batao)\b', lower)
        ) or re.search(r'\b(analyse my laptop and suggest improvements|check my laptop and tell me why it is slow|why is my pc slow|laptop slow kyu hai)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="plan_system_diagnosis",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Storage Analysis & Unnecessary Files Discovery
        if (
            re.search(r'\b(unnecessary|cleanup|clean up|cleaned up|clean|safely review|free up space|junk|clear space)\b', lower)
            and re.search(r'\b(files|storage|disk|laptop|pc|space)\b', lower)
        ) or re.search(r'\b(which files are unnecessary|which files can i safely review|safely review for cleanup|safely delete|kaun se files delete kar sakte hain|unnecessary files batao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="analyze_storage_cleanup",
                parameters={},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Find Duplicate Files
        if re.search(r'\b(duplicate|duplicates|duplicate files|duplicate copies|ek jaisi files)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="find_duplicate_files",
                parameters={"max_results": 10},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Project Folder Analysis ("Analyse this project's folder" / "analyse project <name>")
        project_analysis_match = re.search(r'\b(?:analyse|analyze|inspect|check)\s+(?:the\s+|this\s+)?project(?:\'s)?\s*(?:folder)?\s*([a-zA-Z0-9_\-:\\/ ]*)', lower)
        if project_analysis_match and not re.search(r'\b(?:laptop|pc|computer|disk|storage)\b', lower):
            p_arg = project_analysis_match.group(1).strip()
            if not p_arg or p_arg in {"this", "the", "that", "it", "'s", "this's"}:
                ctx = entity_tracker.get_context(conversation_id) if conversation_id else {}
                if ctx.get("last_project"):
                    p_arg = ctx["last_project"].get("path") or ctx["last_project"].get("name")
                else:
                    from pathlib import Path
                    p_arg = str(Path.cwd())
            if p_arg:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="analyze_project_folder",
                    parameters={"project_path_or_name": p_arg},
                    confidence=0.98,
                    language=lang,
                    fast_path=True,
                )

        # Disk Space & Storage Utilization
        if (
            re.search(r'\b(space|storage|disk|hard drive|drive)\b', lower) and re.search(r'\b(free|khali|available|left|bachi|bacha|capacity|most|kitni|kitna|how much|check|batao)\b', lower)
        ) or re.search(r'\b(free space|disk space|storage space|hard drive|free storage|space available|kitna space|space kitna|kitna storage|storage kitna|free disk|how much storage|storage left|storage remaining|storage available|space khali|khali space)\b', lower):
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

        # Open Project / Open Folder / Open File / Open Path
        open_folder_prefix = re.search(r'\b(?:open|kholo)\s+(?:the\s+|my\s+)?folder\s+([a-zA-Z0-9_\-:\\/ ]+)', lower)
        open_file_prefix = re.search(r'\b(?:open|kholo)\s+(?:the\s+|my\s+)?file\s+([a-zA-Z0-9_\-:\\/ \.]+)', lower)
        open_project_prefix = re.search(r'\b(?:open|kholo)\s+(?:the\s+|my\s+)?project\s+([a-zA-Z0-9_\-:\\/ ]+)', lower)
        folder_suffix_match = re.search(r'\b(?:open|kholo)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\- ]+?)\s+folder\b', lower) or (
            re.search(r'\b(?:open|kholo)\s+(downloads|documents|desktop|videos|music|pictures)\b', lower)
        )

        if open_file_prefix:
            f_cand = open_file_prefix.group(1).strip()
            ctx = entity_tracker.get_context(conversation_id) if conversation_id else {}
            if ctx.get("last_file") and f_cand.lower() == ctx["last_file"].get("path", "").lower():
                f_cand = ctx["last_file"]["path"]
            return IntentResult(
                intent_type="ACTION",
                tool_name="open_file_path",
                parameters={"file_path": f_cand},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        target_folder = None
        if open_folder_prefix:
            target_folder = open_folder_prefix.group(1).strip()
        elif open_project_prefix:
            p_cand = open_project_prefix.group(1).strip()
            ctx = entity_tracker.get_context(conversation_id)
            if p_cand in {"this", "the", "that", "it"} and ctx.get("last_project"):
                target_folder = ctx["last_project"].get("path")
            elif ctx.get("last_project") and p_cand.lower() in ctx["last_project"].get("name", "").lower():
                target_folder = ctx["last_project"].get("path")
            else:
                target_folder = p_cand
        elif folder_suffix_match:
            target_folder = folder_suffix_match.group(1).strip()

        if target_folder:
            if target_folder in {"this", "the", "that", "it"}:
                ctx = entity_tracker.get_context(conversation_id)
                if ctx.get("last_project"):
                    target_folder = ctx["last_project"].get("path")
                elif ctx.get("last_folder"):
                    target_folder = ctx["last_folder"].get("path")
                elif ctx.get("last_file"):
                    target_folder = ctx["last_file"].get("path")
            if target_folder:
                return IntentResult(
                    intent_type="ACTION",
                    tool_name="open_folder",
                    parameters={"folder_path": target_folder},
                    confidence=0.98,
                    language=lang,
                    fast_path=True,
                )

        # Project Inquiry ("Which project did I just ask you about?")
        if re.search(r'\b(which project|what project|kaun sa project|project.*(ask|pucha|baare mein))\b', lower):
            ctx = entity_tracker.get_context(conversation_id) if conversation_id else {}
            last_proj = ctx.get("last_project")
            if last_proj:
                pname = last_proj.get("name", "project")
                ppath = last_proj.get("path", "")
                resp = f"Aapne {pname} project ke baare mein pucha tha (path: {ppath})." if lang == "hinglish" else f"You asked about the {pname} project at {ppath}."
            else:
                resp = "Aapne abhi tak kisi project ke baare mein nahi pucha." if lang == "hinglish" else "You haven't asked about any specific project in this session yet."
            return IntentResult(
                intent_type="QUESTION",
                tool_name="project_inquiry",
                response_text=resp,
                language=lang,
                fast_path=True,
            )

        # Previous Question / Reflection
        if re.search(r'\b(what did i ask|what was my (?:last|previous) question|previous question|pichla sawal|pichhla sawal|pehle kya (?:pucha|poocha|puchha)|maine pehle kya (?:pucha|poocha|puchha))\b', lower):
            from core.conversation_manager import conversation_manager
            db_msgs = conversation_manager.get_messages(conversation_id) if conversation_id else []
            user_msgs = [m for m in db_msgs if m.get("role") == "user"]
            candidates = [
                m for m in user_msgs
                if not re.search(r'\b(what did i ask|last question|previous question|pichla sawal|pehle kya (?:pucha|poocha|puchha))\b', m.get("content", "").lower())
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

        # YouTube in Brave
        if re.search(r'\b(youtube)\b', lower) and re.search(r'\b(brave)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "open youtube in brave", "browser_name": "brave", "url": "https://www.youtube.com"},
                confidence=0.99,
                language=lang,
                fast_path=True,
            )

        # YouTube in Chrome
        if re.search(r'\b(youtube)\b', lower) and re.search(r'\b(chrome)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "open youtube in chrome", "browser_name": "chrome", "url": "https://www.youtube.com"},
                confidence=0.99,
                language=lang,
                fast_path=True,
            )

        # YouTube in Edge
        if re.search(r'\b(youtube)\b', lower) and re.search(r'\b(edge)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "open youtube in edge", "browser_name": "edge", "url": "https://www.youtube.com"},
                confidence=0.99,
                language=lang,
                fast_path=True,
            )

        # YouTube
        if re.search(r'\b(youtube)\b', lower) and re.search(r'\b(open|launch|play|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "youtube", "url": "https://www.youtube.com"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Brave Browser
        if re.search(r'\b(brave|brave browser)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "brave", "browser_name": "brave"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Edge Browser
        if re.search(r'\b(edge|msedge|microsoft edge)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "edge", "browser_name": "edge"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Chrome Browser
        if re.search(r'\b(chrome|google chrome)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "chrome", "browser_name": "chrome"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Firefox Browser
        if re.search(r'\b(firefox|mozilla firefox)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "firefox", "browser_name": "firefox"},
                confidence=0.98,
                language=lang,
                fast_path=True,
            )

        # Generic Browser
        if re.search(r'\b(browser)\b', lower) and re.search(r'\b(open|launch|start|kholo|chalao)\b', lower):
            return IntentResult(
                intent_type="ACTION",
                tool_name="launch_app",
                parameters={"app_name": "browser"},
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

        # 1. Application Launch & Browsers
        if tool_name in {"launch_app", "launch_calculator", "launch_camera", "launch_notepad", "launch_chrome", "launch_vscode", "launch_youtube", "launch_browser", "open_youtube"}:
            res_obj = result.get("result") if isinstance(result.get("result"), dict) else result
            msg = res_obj.get("message") or result.get("message")
            browser = res_obj.get("browser") or params.get("browser_name")
            app = browser or params.get("app_name") or params.get("app") or tool_name.replace("launch_", "").replace("open_", "")

            if status == "error" or res_obj.get("status") == "error":
                if msg:
                    return msg
                app_display = "Microsoft Edge" if str(app).lower() in {"edge", "msedge", "microsoft edge"} else (str(app).capitalize())
                if lang == "hinglish":
                    return f"{app_display} launch nahi ho saka."
                return f"Failed to open {app_display}."

            # Success
            url_target = params.get("url") or res_obj.get("target")
            raw_app_lower = (params.get("app_name") or "").lower()
            raw_url_lower = str(url_target or "").lower()

            if "youtube" in raw_app_lower or "youtube" in raw_url_lower or tool_name == "open_youtube":
                b_target = browser or ("Brave" if "brave" in raw_app_lower else ("Microsoft Edge" if "edge" in raw_app_lower else ("Google Chrome" if "chrome" in raw_app_lower else None)))
                if b_target:
                    if lang == "hinglish":
                        return f"{b_target} mein YouTube khol diya hai."
                    return f"Opened YouTube in {b_target}."
                if lang == "hinglish":
                    return "YouTube browser mein khol diya hai."
                return "Opened YouTube in your browser."

            if str(app).lower() in {"edge", "msedge", "microsoft edge"}:
                app_display = "Microsoft Edge"
            elif browser:
                app_display = browser
            else:
                app_display = str(app) if any(c.isupper() for c in str(app)) else str(app).capitalize()

            if lang == "hinglish":
                return f"{app_display} khol diya hai."
            return f"Opened {app_display}."

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
            free_mb = metrics.get("free_ram_mb", max(0, total_mb - used_mb))
            used_gb = metrics.get("used_ram_gb") or round(used_mb / 1024.0, 1)
            total_gb = metrics.get("total_ram_gb") or round(total_mb / 1024.0, 1)
            free_gb = metrics.get("free_ram_gb") or round(free_mb / 1024.0, 1)

            if lang == "hinglish":
                return f"Aapke laptop ka RAM usage abhi {ram_pct}% hai ({used_gb:.1f} GB use ho rahi hai kul {total_gb:.1f} GB mein se, aur {free_gb:.1f} GB free bachi hai)."
            return f"Your laptop is currently using {used_gb:.1f} GB of RAM out of {total_gb:.1f} GB total ({ram_pct}% RAM usage), with {free_gb:.1f} GB available."

        # 3b. Disk Space & Storage Utilization
        if tool_name == "get_disk_space":
            res_data = result.get("result", {})
            drives = res_data.get("drives", [])
            if not drives:
                msg = res_data.get("message", "Unable to read disk drives.")
                return f"Disk space information could not be retrieved: {msg}" if lang == "english" else f"Disk space ki jankari nahi mil saki: {msg}"

            almost_full = res_data.get("almost_full_drives", [])
            if params.get("almost_full_only"):
                if almost_full:
                    af = almost_full[0]
                    if lang == "hinglish":
                        return f"Aapka {af['drive']} drive lagbhag full ho chuka hai: {af['used_percent']}% used hai aur kewal {af['free_gb']} GB space khali bachi hai {af['total_gb']} GB total mein se."
                    return f"Your {af['drive']} drive is almost full with {af['used_percent']}% used and only {af['free_gb']} GB available out of {af['total_gb']} GB total."
                else:
                    most_used = res_data.get("most_used_drive", "C:")
                    most_pct = res_data.get("most_used_percent", 0)
                    if lang == "hinglish":
                        return f"Aapka koi bhi drive lagbhag full nahi hai. Sabse zyada use hone wala drive {most_used} hai ({most_pct}% used)."
                    return f"None of your drives are currently almost full. Drive with highest usage is {most_used} with {most_pct}% used."

            parts_en = []
            parts_hi = []
            for d in drives:
                d_name = d.get("drive", "")
                free_gb = d.get("free_gb", 0)
                tot_gb = d.get("total_gb", 0)
                used_pct = d.get("used_percent", 0)
                free_pct = d.get("free_percent", round(100.0 - used_pct, 1))
                parts_en.append(f"{d_name} has {free_gb} GB free out of {tot_gb} GB total ({used_pct}% used, {free_pct}% available)")
                parts_hi.append(f"{d_name} drive mein {free_gb} GB free space hai {tot_gb} GB total mein se ({used_pct}% used, {free_pct}% khali)")

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

        # 9. Browser Launching
        if tool_name == "launch_browser":
            res_obj = result.get("result", {})
            b_name = res_obj.get("browser") or params.get("browser_name", "Browser")
            url_target = params.get("url") or res_obj.get("target")
            if status == "success" or res_obj.get("status") == "success":
                if url_target and "youtube" in str(url_target).lower():
                    if lang == "hinglish":
                        return f"{b_name} mein YouTube khol diya hai."
                    return f"Opened YouTube in {b_name}."
                if lang == "hinglish":
                    return f"{b_name} khol diya hai."
                return f"Opened {b_name}."
            else:
                msg = res_obj.get("message") or result.get("message")
                return msg or (f"{b_name} launch nahi ho saka." if lang == "hinglish" else f"Failed to launch {b_name}.")

        # 10. Duplicate Files Discovery
        if tool_name == "find_duplicate_files":
            res_data = result.get("result", {})
            groups = res_data.get("duplicate_groups", [])
            rec_mb = res_data.get("total_recoverable_mb", 0)
            if not groups:
                return "No duplicate files detected in your user directories." if lang == "english" else "Aapke user folders mein koi duplicate files nahi mili."
            first_g = groups[0]
            first_name = first_g["files"][0]["filename"] if first_g.get("files") else "file"
            if lang == "hinglish":
                return f"{len(groups)} duplicate file groups mile hain jisse lagbhag {rec_mb} MB space bacha sakte hain. Pehla duplicate: '{first_name}'."
            return f"Found {len(groups)} duplicate file groups with up to {rec_mb} MB of recoverable space. Example duplicate: '{first_name}' ({first_g['size_mb']} MB)."

        # 11. Multi-Step Diagnostic
        if tool_name == "plan_system_diagnosis":
            res_data = result.get("result", {})
            narrative = res_data.get("narrative")
            if narrative:
                return narrative
            return "System diagnosis complete. Telemetry collected."

        # 12. Storage Analysis
        if tool_name == "analyze_storage_cleanup":
            res_data = result.get("result", {})
            safe_mb = res_data.get("safe_recovery_mb", 0)
            rev_mb = res_data.get("review_recovery_mb", 0)
            tot_mb = res_data.get("total_recoverable_mb", 0)
            tot_gb = round(tot_mb / 1024, 2)
            if lang == "hinglish":
                return f"Storage analysis poora hua: {safe_mb} MB safe temporary cache aur {rev_mb} MB review karne yogya files mili hain (kul {tot_mb} MB space recover ho sakti hai)."
            return f"Storage analysis complete. You can recover up to {tot_gb} GB ({safe_mb} MB safe temporary files + {rev_mb} MB items ready for review)."

        # 13. Project Folder Analysis
        if tool_name == "analyze_project_folder":
            res_data = result.get("result", {})
            pname = res_data.get("project_name", "Project")
            stack = ", ".join(res_data.get("tech_stack", []))
            cnt = res_data.get("total_files", 0)
            sz = res_data.get("total_size_mb", 0)
            if lang == "hinglish":
                return f"'{pname}' project ({stack}): kul {cnt} files hain, total size {sz} MB."
            return f"Project '{pname}' ({stack}): contains {cnt} files, {sz} MB total size."

        # 14. File Recycling (Reversible Deletion)
        if tool_name == "recycle_file_safely":
            res_data = result.get("result") if isinstance(result.get("result"), dict) else result
            f_path = res_data.get("path") or params.get("file_path", "")
            if status == "success" or res_data.get("status") == "success":
                dest = res_data.get("destination", "Recycle Bin")
                if lang == "hinglish":
                    return f"File '{os.path.basename(f_path)}' ko safely {dest} mein bhej diya hai."
                return f"Moved '{os.path.basename(f_path)}' safely to {dest}."
            else:
                msg = res_data.get("message", "Unable to recycle file.")
                if lang == "hinglish":
                    return f"File recycle nahi ho saki: {msg}"
                return f"Failed to recycle file: {msg}"

        # Fallback
        return "Task completed successfully." if lang == "english" else "Operation poora ho gaya hai."


intent_engine = IntentEngine()
