"""
Voice Router & Audio Command Dispatcher for KELA AI Platform.
Routes speech transcripts through central intent classification, entity tracking,
and KelaEngine unified execution.
"""

import re
import os
import datetime
import urllib.parse
import json
import logging
from typing import Dict, Any, Optional, Tuple, List

from core.intent_engine import (
    intent_engine,
    is_wake_word_present,
    detect_language,
    IntentResult,
    WAKE_WORDS,
    HINDI_INDICATORS,
)
from core.tool_registry import tool_registry
from core.entity_tracker import entity_tracker

logger = logging.getLogger("kela.voice.router")


def resolve_voice_intent(text: str, conversation_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Parses natural language voice prompt into structured action metadata using IntentEngine.
    Does NOT execute PC actions; provides intent for security checking in KelaEngine.
    """
    clean = text.strip()
    _, query = is_wake_word_present(clean)
    effective_query = query.strip() or clean
    lang = detect_language(effective_query)

    intent_res: IntentResult = intent_engine.classify_intent(
        effective_query, conversation_id=conversation_id
    )

    action_name = intent_res.tool_name or (
        "conversational_ai" if intent_res.intent_type == "QUESTION" and not intent_res.response_text else
        intent_res.intent_type.lower()
    )

    return {
        "action": action_name,
        "fast_path": intent_res.fast_path,
        "response_text": intent_res.response_text,
        "lang": intent_res.language,
        "clean_query": effective_query,
        "params": intent_res.parameters,
        "intent_type": intent_res.intent_type,
        "clarification_question": intent_res.clarification_question,
        "unsupported_reason": intent_res.unsupported_reason,
        "stop_session": intent_res.stop_session,
        "pause_session": intent_res.pause_session,
        "is_followup": intent_res.is_followup,
        "needs_llm": intent_res.intent_type == "QUESTION" and not intent_res.response_text,
        "data": None,
    }


async def execute_voice_action(
    intent: Dict[str, Any],
    conversation_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Executes the validated voice action using native PC controls via ToolRegistry.
    """
    action = intent["action"]
    lang = intent.get("lang", "english")
    params = intent.get("params", {})
    clean = intent.get("clean_query", "")

    # Fast-path precomputed response (e.g. Identity, Time, Date, Stop/Pause, Greetings)
    if intent.get("response_text"):
        return {
            "handled": True,
            "fast_path": intent.get("fast_path", True),
            "response_text": intent["response_text"],
            "action": action,
            "lang": lang,
            "stop_session": intent.get("stop_session", False),
            "pause_session": intent.get("pause_session", False),
            "data": intent.get("data"),
        }

    # Web search with live snippet summary
    if action == "web_search":
        search_query = params.get("query", clean)
        from pc_control import search_web_in_browser
        search_web_in_browser(search_query)
        search_results = None
        try:
            from browser.engine import BrowserAgent
            browser = BrowserAgent()
            search_results = await browser.search(search_query, limit=3)
        except Exception:
            pass

        if search_results:
            snippets_text = " ".join([f"{r['title']}: {r['snippet']}" for r in search_results if r.get('snippet')])
            snippets_text = re.sub(r'&[a-zA-Z0-9#]+;', ' ', snippets_text)[:400]
            return {
                "handled": True,
                "fast_path": False,
                "action": "web_search_summary",
                "needs_summary": True,
                "query": search_query,
                "snippets": snippets_text,
                "results": search_results,
                "lang": lang,
            }

        resp = f"Maine browser mein '{search_query}' search kar diya hai." if lang == "hinglish" else f"I have opened the web search for '{search_query}' in your browser."
        return {"handled": True, "fast_path": True, "response_text": resp, "action": action, "query": search_query, "lang": lang}

    # Execute tool via ToolRegistry
    tool_res = tool_registry.execute_tool(action, params)

    # Update EntityTracker with result
    if conversation_id is not None:
        entity_tracker.update_from_action_result(
            conversation_id, action, params, tool_res.get("result", {}), lang=lang
        )

    # Format natural spoken response
    intent_obj = IntentResult(
        intent_type="ACTION",
        tool_name=action,
        parameters=params,
        language=lang,
    )
    formatted_resp = intent_engine.format_action_response(intent_obj, tool_res, lang=lang)

    return {
        "handled": tool_res.get("status") in {"success", "requires_approval"},
        "fast_path": True,
        "response_text": formatted_resp,
        "action": action,
        "data": tool_res.get("result"),
        "requires_approval": tool_res.get("requires_approval", False),
        "lang": lang,
    }


async def dispatch_voice_command(
    text: str,
    conversation_id: Optional[int] = None,
    turn_id: Optional[str] = None,
    workspace_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified voice command router.
    Routes execution through central KelaEngine to guarantee session persistence,
    centralized tool risk policy, shared conversation memory, and deduplication.
    """
    from core.engine import kela_engine
    return await kela_engine.process_voice_turn(
        text=text,
        conversation_id=conversation_id,
        turn_id=turn_id,
        workspace_path=workspace_path,
    )
