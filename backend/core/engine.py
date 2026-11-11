import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, AsyncIterator

from .provider_manager import provider_manager, BaseInferenceProvider
from .conversation_manager import conversation_manager
from .context_manager import context_manager
from .prompt_manager import prompt_manager
from .permission_manager import permission_manager
from .tool_registry import tool_registry

logger = logging.getLogger("kela.engine")

def ndjson(data: Dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"

class KelaEngine:
    """
    Central intelligence orchestrator of the KELA AI platform.
    Decoupled from FastAPI routes, browser APIs, and frontend state.
    """

    def __init__(self):
        self.providers = provider_manager
        self.conversations = conversation_manager
        self.context = context_manager
        self.prompts = prompt_manager
        self.permissions = permission_manager
        self.tools = tool_registry

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        conversation_id: Optional[int] = None,
        turn_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """
        Executes an end-to-end conversational turn with streaming tokens,
        evidence injection, data integrity, and atomic cancellation cleanup.
        """
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            yield ndjson({"error": "A user message is required."})
            return

        last_user_message = user_messages[-1].get("content", "").strip()

        # 1. Resolve or create persistent conversation
        if not conversation_id:
            # Create new conversation with title derived from first message
            title = last_user_message[:40] or "New chat"
            conv_data = self.conversations.create_conversation(title=title)
            conversation_id = conv_data["id"]
        else:
            # If request only passed the latest message, load prior session history from SQLite
            if len(messages) <= 1:
                db_msgs = self.conversations.get_messages(conversation_id)
                if db_msgs:
                    history = []
                    for dm in db_msgs:
                        if dm.get("content") == last_user_message and dm.get("role") == "user":
                            continue
                        history.append({"role": dm["role"], "content": dm["content"]})
                    history.append({"role": "user", "content": last_user_message})
                    messages = history

        active_turn_id = turn_id or f"turn_{int(asyncio.get_event_loop().time() * 1000)}"

        # 2. Acquire concurrency lock to prevent duplicate turn execution
        if not self.conversations.acquire_turn_lock(conversation_id, active_turn_id):
            yield ndjson({
                "conversation_id": conversation_id,
                "error": "A request for this conversation turn is already actively executing.",
            })
            return

        try:
            # Save user message immediately to SQLite (idempotent via turn_id)
            self.conversations.save_user_message(
                conversation_id=conversation_id,
                content=last_user_message,
                client_message_id=active_turn_id,
            )

            # Signal conversation ID to client
            yield ndjson({"conversation_id": conversation_id})

            # 3. Assemble System Context and Preferences
            project_context = self.context.get_workspace_context(workspace_path) if workspace_path else ""
            user_prefs = self.context.get_user_preferences_block()
            system_msg = self.prompts.build_system_message(
                project_context=project_context,
                user_preferences=user_prefs,
            )

            evidence_msgs: List[Dict[str, str]] = []

            # 4. Automatic Web Evidence if URL present in user prompt
            urls = re.findall(r"https?://[^\s<>\"']+", last_user_message)
            if urls:
                try:
                    from browser.engine import BrowserAgent
                    browser = BrowserAgent()
                    for target_url in urls[:2]:
                        yield ndjson({"step": f"Browsing live website: {target_url}..."})
                        res = await browser.navigate(target_url)
                        if res.get("success") and res.get("page"):
                            page = res["page"]
                            title = page.get("title", target_url)
                            text = page.get("text_preview", "")
                            yield ndjson({"step": f"Extracted content from '{title}' ({len(text)} chars)"})
                            evidence_msgs.append(
                                self.prompts.format_untrusted_evidence(title, target_url, text)
                            )
                except Exception as exc:
                    logger.warning("Auto-browse failed: %s", exc)

            # 5. Automatic Document Evidence if attachment referenced
            att_matches = re.findall(r"\[Referenced Attachments:\s*([^\]]+)\]", last_user_message)
            if att_matches and workspace_path:
                try:
                    from documents.processor import process_document
                    storage_dir = Path(workspace_path) / ".nexus_uploads"
                    for att_line in att_matches:
                        for fname in [f.strip() for f in att_line.split(",") if f.strip()]:
                            cand = [
                                storage_dir / fname,
                                Path(workspace_path) / fname,
                                Path.home() / "Downloads" / fname,
                            ]
                            target_file = next((p for p in cand if p.is_file()), None)
                            if target_file:
                                doc_info = process_document(target_file)
                                doc_content = doc_info.get("content", "")
                                if doc_content:
                                    yield ndjson({"step": f"Analyzed attachment '{fname}'"})
                                    evidence_msgs.append(
                                        self.prompts.format_untrusted_evidence(fname, str(target_file), doc_content)
                                    )
                except Exception as exc:
                    logger.warning("Document processor failed: %s", exc)

            # 6. Assemble and Prune Message List within Token Budget
            assembled_messages = self.prompts.assemble_model_messages(
                raw_messages=messages,
                system_message=system_msg,
                evidence_messages=evidence_msgs,
            )
            pruned_messages = self.context.prune_conversation_history(assembled_messages)

            # 7. Stream Model Inference via Provider Architecture
            assistant_chunks: List[str] = []
            target_model = model or getattr(self.providers.get_active_provider(), "default_model", None)

            async for event in self.providers.execute_with_fallback(pruned_messages, model=target_model):
                if "error" in event:
                    yield ndjson({"error": event["error"]})
                    return

                if "step" in event:
                    yield ndjson({"step": event["step"]})
                    continue

                if "token" in event:
                    token = event["token"]
                    assistant_chunks.append(token)
                    yield ndjson({"token": token})

                if event.get("done"):
                    completed_answer = "".join(assistant_chunks).strip()
                    if completed_answer:
                        # 8. Persist completed assistant response atomically
                        self.conversations.save_assistant_message(
                            conversation_id=conversation_id,
                            content=completed_answer,
                            client_message_id=f"{active_turn_id}:assistant",
                        )
                    yield ndjson({"done": True, "conversation_id": conversation_id})
                    return

        except asyncio.CancelledError:
            logger.info("Generation cancelled for conversation %s, turn %s", conversation_id, active_turn_id)
            yield ndjson({"cancelled": True, "conversation_id": conversation_id})
            raise
        except Exception as e:
            logger.error("Engine execution failure: %s", e)
            yield ndjson({"error": f"Internal execution error: {str(e)}"})
        finally:
            self.conversations.release_turn_lock(conversation_id, active_turn_id)

    async def process_voice_turn(
        self,
        text: str,
        conversation_id: Optional[int] = None,
        turn_id: Optional[str] = None,
        workspace_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Unifies voice interaction with KELA's central engine, persistence,
        permission management, tool risk checking, and provider fallback.
        """
        from voice.router import resolve_voice_intent, execute_voice_action, is_wake_word_present, detect_language

        clean_text = text.strip()
        _, stripped_query = is_wake_word_present(clean_text)
        effective_query = stripped_query.strip() or clean_text

        # 1. Resolve or create persistent conversation session in SQLite (Requirement 4)
        if not conversation_id:
            title = f"Voice: {effective_query[:30]}" if effective_query else "Voice Conversation"
            conv_data = self.conversations.create_conversation(title=title)
            conversation_id = conv_data["id"]
        else:
            existing = self.conversations.get_conversation(conversation_id)
            if not existing:
                title = f"Voice: {effective_query[:30]}" if effective_query else "Voice Conversation"
                conv_data = self.conversations.create_conversation(title=title)
                conversation_id = conv_data["id"]

        active_turn_id = turn_id or f"voice_{int(asyncio.get_event_loop().time() * 1000)}"

        # 2. Concurrency lock to prevent duplicate turn execution (Requirement 10)
        if not self.conversations.acquire_turn_lock(conversation_id, active_turn_id):
            logger.warning("Duplicate turn execution prevented: conv=%s, turn=%s", conversation_id, active_turn_id)
            return {
                "conversation_id": conversation_id,
                "turn_id": active_turn_id,
                "handled": False,
                "error": "Duplicate turn execution prevented.",
                "response_text": "",
                "action": "duplicate_suppressed",
            }

        lang = detect_language(clean_text)

        try:
            # 3. Persist voice user message immediately to SQLite (Requirement 5)
            if clean_text:
                self.conversations.save_user_message(
                    conversation_id=conversation_id,
                    content=clean_text,
                    client_message_id=active_turn_id,
                )

            # 4. Resolve voice intent
            intent = resolve_voice_intent(clean_text)
            action_name = intent["action"]
            lang = intent.get("lang", lang)

            # 5. Tool Registry Risk & Action Permission Check (Requirements 7 & 8)
            risk = self.tools.get_tool_risk(action_name)
            if risk == "RED":
                refuse_text = (
                    "Yeh operation voice mode mein allowed nahi hai."
                    if lang == "hinglish"
                    else f"The '{action_name}' operation is not permitted via voice."
                )
                self.conversations.save_assistant_message(
                    conversation_id=conversation_id,
                    content=refuse_text,
                    client_message_id=f"{active_turn_id}:assistant",
                )
                return {
                    "conversation_id": conversation_id,
                    "turn_id": active_turn_id,
                    "handled": False,
                    "risk": risk,
                    "response_text": refuse_text,
                    "action": action_name,
                    "lang": lang,
                }
            elif risk == "AMBER":
                approval_text = (
                    f"Operation '{action_name}' ke liye explicit approval ki zaroorat hai."
                    if lang == "hinglish"
                    else f"Operation '{action_name}' requires explicit approval in workspace."
                )
                self.conversations.save_assistant_message(
                    conversation_id=conversation_id,
                    content=approval_text,
                    client_message_id=f"{active_turn_id}:assistant",
                )
                return {
                    "conversation_id": conversation_id,
                    "turn_id": active_turn_id,
                    "handled": False,
                    "risk": risk,
                    "requires_approval": True,
                    "response_text": approval_text,
                    "action": action_name,
                    "lang": lang,
                }

            # 6. Execute safe action or delegate to inference provider
            exec_result = await execute_voice_action(intent)
            response_text = exec_result.get("response_text", "")

            if exec_result.get("needs_summary"):
                # Summarize web search results using active inference provider
                snippets = exec_result.get("snippets", "")
                q = exec_result.get("query", "")
                summary_prompt = (
                    f"Live search results for '{q}': {snippets}. "
                    "Summarize the core finding into ONE conversational spoken sentence for Kunal."
                )
                voice_system = (
                    "You are KELA, an ultra-fast voice assistant for Kunal Singh. "
                    "Answer in ONE short, natural spoken sentence (under 25 words). "
                    "Never use markdown, lists, code, or quotes."
                )
                provider = self.providers.get_active_provider()
                try:
                    summary_resp = await asyncio.wait_for(
                        provider.generate_chat(
                            [
                                {"role": "system", "content": voice_system},
                                {"role": "user", "content": summary_prompt},
                            ],
                            options={"temperature": 0.4, "num_predict": 30},
                        ),
                        timeout=4.0,
                    )
                    cleaned = re.sub(r'[*_#`[\]()"\n]', ' ', summary_resp).strip()
                    if cleaned:
                        response_text = f"I searched the web for {q}. {cleaned}"
                    else:
                        response_text = f"I searched the web for {q} and opened the results in your browser."
                except Exception as ex:
                    logger.warning("Web search summary error: %s", ex)
                    response_text = f"I searched the web for {q} and opened the results in your browser."

            elif exec_result.get("needs_llm"):
                # Conversational query with recent conversation context (Requirement 6)
                voice_system = (
                    "You are KELA, an ultra-fast voice assistant for Kunal Singh. "
                    "Answer in ONE short, natural spoken sentence (under 25 words). "
                    "Never use markdown, lists, code, or quotes."
                )
                past_messages = self.conversations.get_messages(conversation_id)
                recent_history: List[Dict[str, str]] = []
                for m in past_messages[-5:]:
                    if m.get("content") == clean_text and m.get("role") == "user":
                        continue
                    recent_history.append({"role": m["role"], "content": m["content"]})

                query_messages = [
                    {"role": "system", "content": voice_system},
                    *recent_history,
                    {"role": "user", "content": effective_query or clean_text},
                ]

                provider = self.providers.get_active_provider()
                try:
                    llm_raw = await asyncio.wait_for(
                        provider.generate_chat(
                            query_messages,
                            options={"temperature": 0.4, "num_predict": 30},
                        ),
                        timeout=4.0,
                    )
                    cleaned = re.sub(r'[*_#`[\]()"\n]', ' ', llm_raw).strip()
                    if cleaned:
                        response_text = cleaned
                    else:
                        response_text = (
                            "Haan Kunal, main sun raha hoon. Kya karna hai?"
                            if lang == "hinglish"
                            else "I am right here with you, Kunal. How can I help next?"
                        )
                except Exception as ex:
                    logger.warning("Voice LLM error: %s", ex)
                    response_text = (
                        "Haan Kunal, main sun raha hoon. Kya karna hai?"
                        if lang == "hinglish"
                        else "I am right here with you, Kunal. How can I help next?"
                    )

            # 7. Persist completed assistant response to SQLite (Requirement 5)
            if response_text:
                self.conversations.save_assistant_message(
                    conversation_id=conversation_id,
                    content=response_text,
                    client_message_id=f"{active_turn_id}:assistant",
                )

            # 8. Return response payload compatible with frontend contract
            return {
                "conversation_id": conversation_id,
                "turn_id": active_turn_id,
                "handled": exec_result.get("handled", True),
                "fast_path": exec_result.get("fast_path", False),
                "response_text": response_text,
                "action": exec_result.get("action", action_name),
                "lang": lang,
                "stop_session": exec_result.get("stop_session", False),
                "pause_session": exec_result.get("pause_session", False),
                "data": exec_result.get("data"),
            }

        except Exception as err:
            logger.error("Error in process_voice_turn: %s", err, exc_info=True)
            fallback = (
                "Kuch takleef aayi, kripya dobara boliye."
                if lang == "hinglish"
                else "Sorry, I encountered an internal error processing that voice command."
            )
            return {
                "conversation_id": conversation_id,
                "turn_id": active_turn_id,
                "handled": False,
                "error": str(err),
                "response_text": fallback,
                "action": "error",
                "lang": lang,
            }
        finally:
            self.conversations.release_turn_lock(conversation_id, active_turn_id)


kela_engine = KelaEngine()
