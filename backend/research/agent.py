import json
import logging
from typing import AsyncGenerator
import httpx

from connectors.registry import ConnectorRegistry
from database import save_message
from knowledge.engine import search_knowledge_base
from memory.manager import MemoryManager

logger = logging.getLogger("nexus.research")
OLLAMA_URL = "http://127.0.0.1:11434"


def ndjson(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


async def research_stream(
    query: str,
    conversation_id: int,
    turn_id: str,
    workspace_path: str,
    depth: str = "standard",
    sources: list[str] | None = None,
    model_name: str = "qwen2.5-coder:7b",
) -> AsyncGenerator[str, None]:
    yield ndjson({"conversation_id": conversation_id})
    yield ndjson({
        "type": "research_plan",
        "step": "Formulating research plan and identifying evidence sources...",
        "depth": depth,
    })

    top_k = 3 if depth == "quick" else (8 if depth == "deep" else 5)
    evidence_blocks = []
    collected_sources = []

    # 0. Check for directly referenced attachments in the research query
    import re
    from pathlib import Path
    att_matches = re.findall(r"\[Referenced Attachments:\s*([^\]]+)\]", query)
    if att_matches:
        from documents.processor import process_document
        storage_dir = Path(workspace_path) / ".nexus_uploads"
        for att_str in att_matches:
            for fname in [f.strip() for f in att_str.split(",") if f.strip()]:
                cands = [storage_dir / fname, Path(workspace_path) / fname, Path.home() / "Downloads" / fname]
                target_f = next((p for p in cands if p.is_file()), None)
                if target_f:
                    try:
                        doc = process_document(target_f)
                        c_id = f"[{len(collected_sources) + 1}]"
                        collected_sources.append({
                            "citation_id": c_id,
                            "title": f"Attached Document: {fname}",
                            "path": str(target_f),
                            "type": "attached_document",
                            "snippet": doc.get("content", "")[:300],
                            "score": 1.0,
                        })
                        count_label = f"{doc.get('total_slides', doc.get('total_pages', 'structured'))} sections"
                        evidence_blocks.insert(0, f"Source {c_id}: {fname} ({doc.get('document_type', 'document')})\nContent:\n{doc.get('content', '')}\n")
                        yield ndjson({
                            "type": "research_step",
                            "step": f"Extracted and analyzed primary attached document '{fname}' ({count_label})...",
                        })
                    except Exception as e:
                        logger.warning("Error processing attachment %s: %s", fname, e)

    # 0b. Check for live web URLs in query
    urls = re.findall(r"https?://[^\s<>\"']+", query)
    if urls:
        from browser.engine import BrowserAgent
        browser = BrowserAgent()
        for u in urls[:2]:
            yield ndjson({"type": "research_step", "step": f"Browsing live web evidence from {u}..."})
            try:
                res = await browser.navigate(u)
                if res.get("success") and res.get("page"):
                    page = res["page"]
                    c_id = f"[{len(collected_sources) + 1}]"
                    collected_sources.append({
                        "citation_id": c_id,
                        "title": page.get("title", u),
                        "path": u,
                        "type": "web_page",
                        "snippet": page.get("description", "") or page.get("text_preview", "")[:200],
                        "score": 1.0,
                    })
                    evidence_blocks.append(f"Source {c_id}: Live Web Page '{page.get('title', u)}'\nURL: {u}\nContent:\n{page.get('text_preview', '')}\n")
            except Exception as e:
                logger.warning("Failed to browse %s: %s", u, e)

    # 1. Search indexed Knowledge Base
    clean_search_query = re.sub(r"\[Referenced Attachments:[^\]]+\]", "", query).strip()
    yield ndjson({
        "type": "research_step",
        "step": f"Retrieving grounded evidence from Knowledge Base (top {top_k} matches)...",
    })
    kb_results = search_knowledge_base(clean_search_query or query, top_k=top_k)
    for r in kb_results:
        collected_sources.append({
            "citation_id": r["citation_id"],
            "title": r["title"],
            "path": r["file_path"],
            "type": "knowledge_doc",
            "snippet": r["snippet"],
            "score": r["score"],
        })
        lines_info = f" (Lines {r['start_line']}-{r['end_line']})" if r.get("start_line") else ""
        evidence_blocks.append(
            f"Source {r['citation_id']}: {r['title']}{lines_info}\nPath: {r['file_path']}\n"
            f"Content:\n{r['content']}\n"
        )

    # 2. Check Database Connectors if enabled or relevant
    try:
        connectors = ConnectorRegistry.list_all()
        for conn_meta in connectors:
            if conn_meta.get("id") == "web_search":
                continue
            c_inst = ConnectorRegistry.get(conn_meta["id"])
            if not c_inst:
                continue
            schema = c_inst.inspect_schema()
            table_names = [t["name"] for t in schema.get("tables", [])]
            # If query mentions a table or database keyword
            if any(t.lower() in query.lower() for t in table_names):
                yield ndjson({
                    "type": "research_step",
                    "step": f"Inspecting matching database connector: {conn_meta['name']}...",
                })
                # Safe read-only inspection summary
                c_id = f"[{len(collected_sources) + 1}]"
                collected_sources.append({
                    "citation_id": c_id,
                    "title": f"Database: {conn_meta['name']}",
                    "path": conn_meta.get("config", {}).get("db_path", conn_meta.get("id")),
                    "type": "database",
                    "snippet": f"Tables: {', '.join(table_names[:10])}",
                    "score": 0.9,
                })
                evidence_blocks.append(
                    f"Source {c_id}: Database {conn_meta['name']}\n"
                    f"Available Tables: {', '.join(table_names)}\n"
                )
    except Exception as exc:
        logger.debug("Database inspection during research skipped: %s", exc)

    # 3. Check Web Search if explicitly enabled
    web_conn = ConnectorRegistry.get("web_search")
    if web_conn and getattr(web_conn, "enabled", False):
        yield ndjson({
            "type": "research_step",
            "step": "Querying authorized web search connector...",
        })
        try:
            web_res = web_conn.execute_query(query, max_rows=3)
            for row in web_res.get("rows", []):
                c_id = f"[{len(collected_sources) + 1}]"
                title = row[0] if len(row) > 0 else "Web Result"
                url = row[1] if len(row) > 1 else ""
                collected_sources.append({
                    "citation_id": c_id,
                    "title": title,
                    "path": url,
                    "type": "web",
                    "snippet": title,
                    "score": 0.8,
                })
                evidence_blocks.append(f"Source {c_id}: {title}\nURL: {url}\n")
        except Exception:
            pass

    yield ndjson({
        "type": "evidence_summary",
        "sources_count": len(collected_sources),
        "sources": collected_sources,
    })

    # Memory & instructions injection
    memory_injection = MemoryManager.build_context_injection(workspace_path)

    system_prompt = (
        "You are Nexus AI's Deep Research and Reasoning Agent.\n"
        "Your mission is to provide rigorous, evidence-grounded research answers.\n\n"
        "STRICT RESEARCH RULES:\n"
        "1. Every single factual claim MUST be grounded in the provided Evidence Sources.\n"
        "2. Use bracketed numeric citations like [1], [2] referencing the corresponding Source number whenever stating a fact.\n"
        "3. Explicitly structure your output with these sections:\n"
        "   ### Executive Summary\n"
        "   ### Verified Findings (with citations)\n"
        "   ### Inferences & Working Estimates (clearly labeled as unverified deductions)\n"
        "   ### Unknowns & Knowledge Gaps (state explicitly what the available sources cannot answer)\n"
        "   ### Cited Sources\n"
        "4. If no sources contain information to answer the question, state honestly: 'The authorized knowledge sources do not contain sufficient evidence to answer this question.' NEVER fabricate citations or facts.\n"
    )

    if memory_injection:
        system_prompt += f"\n{memory_injection}\n"

    evidence_text = "\n---\n".join(evidence_blocks) if evidence_blocks else "No local documents matched this query."

    user_prompt = (
        f"RESEARCH QUESTION:\n{query}\n\n"
        f"EVALUATED EVIDENCE SOURCES:\n{evidence_text}\n\n"
        "Synthesize a thorough, objective research analysis following the strict research rules."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "options": {"num_ctx": 8192, "temperature": 0.2},
    }

    assistant_parts = []
    try:
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("error"):
                        yield ndjson({"error": str(event["error"])})
                        return

                    content = event.get("message", {}).get("content", "")
                    if content:
                        assistant_parts.append(content)
                        yield ndjson({"token": content})

                    if event.get("done"):
                        answer = "".join(assistant_parts)
                        if answer:
                            save_message(
                                conversation_id,
                                "assistant",
                                answer,
                                client_message_id=f"{turn_id}:assistant",
                            )
                        yield ndjson({
                            "done": True,
                            "sources": collected_sources,
                            "conversation_id": conversation_id,
                        })
                        return

    except Exception as exc:
        logger.exception("Error streaming research response: %s", exc)
        yield ndjson({"error": f"Research generation encountered an error: {exc}"})
