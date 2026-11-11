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


kela_engine = KelaEngine()
