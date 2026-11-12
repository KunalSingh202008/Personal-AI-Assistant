import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import database
from database import initialize_database, get_connection
from knowledge.chunker import chunk_text, chunk_sections
from knowledge.embeddings import (
    cosine_similarity,
    generate_local_embedding,
    FastLocalEmbeddingProvider,
    embedding_manager,
)
from knowledge.engine import (
    create_knowledge_base,
    delete_indexed_document,
    delete_knowledge_base,
    get_knowledge_base_details,
    index_directory,
    index_file,
    ingest_uploaded_file,
    list_indexed_documents,
    list_knowledge_bases,
    reindex_knowledge_base,
    search_knowledge_base,
)
from knowledge.parser import (
    DocumentSection,
    parse_csv_content,
    parse_file,
    sanitize_filename,
    validate_file_safety,
)


class KnowledgeEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_knowledge.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_chunker_bounds_and_overlap(self):
        sample = ("Line 1 paragraph.\n\n" * 10) + ("Code block here.\n" * 5)
        chunks = chunk_text(sample, chunk_size=100, overlap=20)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertIn("content", chunk)
            self.assertIn("start_line", chunk)
            self.assertIn("end_line", chunk)
            self.assertGreater(chunk["token_count"], 0)

    def test_local_embeddings_and_cosine_similarity(self):
        v1 = generate_local_embedding("FastAPI backend with Python 3.14")
        v2 = generate_local_embedding("FastAPI python web server")
        v3 = generate_local_embedding("baking sourdough bread at home")

        sim_related = cosine_similarity(v1, v2)
        sim_unrelated = cosine_similarity(v1, v3)

        self.assertGreater(sim_related, 0.3)
        self.assertGreater(sim_related, sim_unrelated)

    def test_csv_parser_formatting(self):
        csv_text = "id,name,role\n1,Alice,Engineer\n2,Bob,Designer\n"
        parsed = parse_csv_content(csv_text)
        self.assertIn("CSV Dataset Summary", parsed)
        self.assertIn("| id | name | role |", parsed)
        self.assertIn("| 1 | Alice | Engineer |", parsed)

    def test_index_file_incremental_and_search(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "notes.md"
            tmp_path.write_text("# KELA Architecture\n\nKELA is an autonomous personal AI operating system.\nIt provides deep research, coding agent, and memory.", encoding="utf-8")

            # 1. Index file
            res1 = index_file(tmp_path, kb_id="default")
            self.assertEqual(res1["status"], "indexed")
            doc_id = res1["document_id"]

            # 2. Re-indexing unchanged file should be skipped
            res2 = index_file(tmp_path, kb_id="default")
            self.assertEqual(res2["status"], "skipped")
            self.assertEqual(res2["reason"], "unchanged")

            # 3. Search query matching indexed content
            search_results = search_knowledge_base("autonomous personal operating system", kb_id="default", top_k=3)
            self.assertGreater(len(search_results), 0)
            self.assertEqual(search_results[0]["title"], "notes.md")
            self.assertIn("KELA", search_results[0]["content"])

            # 4. Delete document
            deleted = delete_indexed_document(doc_id)
            self.assertTrue(deleted)

            # 5. Search after deletion
            after_search = search_knowledge_base("autonomous personal operating system", kb_id="default", top_k=3)
            matching = [r for r in after_search if r["document_id"] == doc_id]
            self.assertEqual(len(matching), 0)

    def test_multi_kb_strict_isolation(self):
        """
        Critical Multi-Dataset Requirement:
        Data indexed in KB-A must NEVER leak or be retrieved when querying KB-B.
        """
        # Create two distinct knowledge bases
        kb_finance = create_knowledge_base(name="Finance Workspace", kb_id="kb_finance_test")
        kb_medical = create_knowledge_base(name="Medical Records", kb_id="kb_medical_test")

        self.assertEqual(kb_finance["id"], "kb_finance_test")
        self.assertEqual(kb_medical["id"], "kb_medical_test")

        with tempfile.TemporaryDirectory() as tmp_dir:
            fin_path = Path(tmp_dir) / "q4_financials.txt"
            fin_path.write_text(
                "Company Q4 consolidated revenue reached $45.8 million, with cloud ARR growing 62% year-over-year.",
                encoding="utf-8",
            )

            med_path = Path(tmp_dir) / "patient_cardiology.txt"
            med_path.write_text(
                "Electrocardiogram indicates sinus bradycardia with ventricular rate of 48 beats per minute.",
                encoding="utf-8",
            )

            res_fin = index_file(fin_path, kb_id="kb_finance_test")
            self.assertEqual(res_fin["status"], "indexed")

            res_med = index_file(med_path, kb_id="kb_medical_test")
            self.assertEqual(res_med["status"], "indexed")

            # Query Finance KB for cardiology topic -> must NEVER return patient_cardiology.txt
            fin_leak_check = search_knowledge_base("sinus bradycardia ventricular beats", kb_id="kb_finance_test")
            for r in fin_leak_check:
                self.assertEqual(r["kb_id"], "kb_finance_test")
                self.assertNotEqual(r["title"], "patient_cardiology.txt")
                self.assertNotIn("bradycardia", r["content"])

            # Query Medical KB for financial topic -> must NEVER return q4_financials.txt
            med_leak_check = search_knowledge_base("consolidated revenue cloud ARR", kb_id="kb_medical_test")
            for r in med_leak_check:
                self.assertEqual(r["kb_id"], "kb_medical_test")
                self.assertNotEqual(r["title"], "q4_financials.txt")
                self.assertNotIn("consolidated revenue", r["content"])

            # Valid query to Finance KB
            fin_results = search_knowledge_base("consolidated revenue ARR", kb_id="kb_finance_test")
            self.assertGreater(len(fin_results), 0)
            self.assertEqual(fin_results[0]["title"], "q4_financials.txt")
            self.assertEqual(fin_results[0]["kb_id"], "kb_finance_test")
            self.assertNotIn("bradycardia", fin_results[0]["content"])

            # Valid query to Medical KB
            med_results = search_knowledge_base("bradycardia ventricular rate", kb_id="kb_medical_test")
            self.assertGreater(len(med_results), 0)
            self.assertEqual(med_results[0]["title"], "patient_cardiology.txt")
            self.assertEqual(med_results[0]["kb_id"], "kb_medical_test")
            self.assertNotIn("consolidated revenue", med_results[0]["content"])

        # Cleanup test KBs
        delete_knowledge_base("kb_finance_test")
        delete_knowledge_base("kb_medical_test")

    def test_document_sections_and_genuine_citations(self):
        """
        Verifies section parsing preservation of genuine page numbers and sheet names,
        preventing hallucinated or fabricated citations.
        """
        sections = [
            DocumentSection(
                content="Chapter 1: Foundational Quantum Mechanics. Energy states are quantized at hbar * omega.",
                page_number=1,
                section_title="Chapter 1",
            ),
            DocumentSection(
                content="Chapter 2: Perturbation Theory. The Hamiltonian is split into H0 and V.",
                page_number=2,
                section_title="Chapter 2",
            ),
            DocumentSection(
                content="Financial Model - Q1 P&L Sheet: Gross revenue $1.2M, operating expenses $400K.",
                sheet_name="Income Statement",
                section_title="Q1 P&L",
            ),
        ]

        chunks = chunk_sections(sections, chunk_size=200, overlap=30)
        self.assertEqual(len(chunks), 3)

        # Verify page number preserved
        self.assertEqual(chunks[0]["page_number"], 1)
        self.assertIsNone(chunks[0]["sheet_name"])
        self.assertEqual(chunks[1]["page_number"], 2)

        # Verify sheet name preserved
        self.assertEqual(chunks[2]["sheet_name"], "Income Statement")
        self.assertIsNone(chunks[2]["page_number"])

    def test_security_bounds_and_input_validation(self):
        """Test path traversal protection and file size/type boundaries."""
        # Path traversal sanitization
        malicious = "../../../secret/passwd.txt"
        sanitized = sanitize_filename(malicious)
        self.assertNotIn("..", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("\\", sanitized)

        # Extension validation
        with tempfile.NamedTemporaryFile(suffix=".exe") as f:
            f.write(b"MZ\x90\x00")
            f.flush()
            with self.assertRaises(ValueError) as ctx:
                validate_file_safety(Path(f.name))
            self.assertIn("Unsupported file type", str(ctx.exception))

        # Size boundary (> 50 MB)
        with self.assertRaises(ValueError) as ctx:
            ingest_uploaded_file(
                filename="huge.txt",
                content_bytes=b"0" * (51 * 1024 * 1024),
                kb_id="default",
            )
        self.assertIn("exceeds 50 MB limit", str(ctx.exception))

    def test_embedding_manager_and_vector_properties(self):
        """Verify FastLocalEmbeddingProvider generates 128d normalized vectors deterministically."""
        provider = FastLocalEmbeddingProvider()
        vec1 = asyncio.run(provider.embed_query("Distributed consensus via Raft algorithm"))
        vec2 = asyncio.run(provider.embed_query("Distributed consensus via Raft algorithm"))

        self.assertEqual(len(vec1), 128)
        self.assertEqual(vec1, vec2, "Local embeddings must be deterministic!")

        # Verify L2 normalization: norm should equal ~1.0
        norm = sum(x * x for x in vec1) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=3)

        # Verify embedding manager status
        status = asyncio.run(embedding_manager.get_all_status())
        providers = [s["provider"] for s in status]
        self.assertIn("local-fast", providers)
        local_fast_info = next(s for s in status if s["provider"] == "local-fast")
        self.assertTrue(local_fast_info["available"])
        self.assertEqual(local_fast_info["dimension"], 128)

    def test_kb_deletion_cascading(self):
        """Verify deleting a knowledge base cleanly purges docs, chunks, and FTS entries."""
        kb_id = "kb_cascade_test"
        create_knowledge_base(name="Cascade Test", kb_id=kb_id)

        with tempfile.TemporaryDirectory() as tmp_dir:
            doc_path = Path(tmp_dir) / "test_doc.txt"
            doc_path.write_text("UniqueCascadeToken12345 should be wiped on KB deletion.", encoding="utf-8")
            index_file(doc_path, kb_id=kb_id)

        # Ensure indexed
        docs_before = list_indexed_documents(kb_id=kb_id)
        self.assertEqual(len(docs_before), 1)
        search_before = search_knowledge_base("UniqueCascadeToken12345", kb_id=kb_id)
        self.assertGreater(len(search_before), 0)

        # Delete KB
        deleted = delete_knowledge_base(kb_id)
        self.assertTrue(deleted)

        # Verify wiped
        docs_after = list_indexed_documents(kb_id=kb_id)
        self.assertEqual(len(docs_after), 0)
        search_after = search_knowledge_base("UniqueCascadeToken12345", kb_id=kb_id)
        self.assertEqual(len(search_after), 0)

    def test_kela_engine_rag_retrieval_and_source_events(self):
        """Verify KelaEngine.chat_stream integrates RAG retrieval and emits citation events."""
        import json
        from core.engine import KelaEngine
        from core.provider_manager import BaseInferenceProvider

        class MockProvider(BaseInferenceProvider):
            def __init__(self):
                self.last_messages = []

            async def chat(self, messages, model=None, options=None):
                self.last_messages = messages
                return "The server listening port is 8001 based on internal architecture docs."

            async def stream_chat(self, messages, model=None, options=None):
                self.last_messages = messages
                yield {"token": "The server listening port is 8001 based on internal architecture docs."}
                yield {"done": True}

            async def health_check(self):
                return {"available": True}

        mock_prov = MockProvider()
        engine = KelaEngine()

        kb_id = "kb_rag_stream_test"
        create_knowledge_base(name="RAG Stream Test", kb_id=kb_id)

        with tempfile.TemporaryDirectory() as tmp_dir:
            doc_path = Path(tmp_dir) / "network_spec.txt"
            doc_path.write_text("Infrastructure spec: The primary server listening port is 8001 and DB is SQLite.", encoding="utf-8")
            index_file(doc_path, kb_id=kb_id)

        async def run_stream():
            events = []
            async for ev_raw in engine.chat_stream(
                [{"role": "user", "content": "What is the primary server listening port?"}],
                kb_id=kb_id,
            ):
                try:
                    events.append(json.loads(ev_raw.strip()))
                except Exception:
                    pass
            return events

        with patch.object(engine.providers, "get_active_provider", return_value=mock_prov):
            events = asyncio.run(run_stream())

        # Verify sources event was emitted
        source_events = [e for e in events if e.get("type") == "sources"]
        self.assertGreater(len(source_events), 0, "KelaEngine must emit 'sources' event when RAG finds matches")
        sources = source_events[0]["sources"]
        self.assertGreater(len(sources), 0)
        self.assertEqual(sources[0]["title"], "network_spec.txt")
        self.assertIn("8001", sources[0]["content"])

        # Verify prompt injection barrier was applied to provider messages
        combined_prompts = " ".join(m.get("content", "") for m in mock_prov.last_messages)
        self.assertIn("<untrusted_reference_data", combined_prompts)
        self.assertIn("passive external reference data", combined_prompts)

        delete_knowledge_base(kb_id)

    def test_json_and_jsonl_parsers(self):
        """Verify structured JSON and JSONL datasets are parsed into readable summaries."""
        from knowledge.parser import parse_json_content, parse_jsonl_content

        # 1. JSON Array
        arr_str = '[{"id": 1, "product": "Solar Panel"}, {"id": 2, "product": "Battery Pack"}]'
        parsed_arr = parse_json_content(arr_str)
        self.assertIn("JSON Dataset: Array of 2 items", parsed_arr)
        self.assertIn("Solar Panel", parsed_arr)

        # 2. JSON Object
        obj_str = '{"company": "KELA Aerospace", "version": "3.0", "status": "active"}'
        parsed_obj = parse_json_content(obj_str)
        self.assertIn("JSON Document: Object with 3 root keys", parsed_obj)
        self.assertIn("KELA Aerospace", parsed_obj)

        # 3. JSONL Lines
        jsonl_str = '{"user": "alice", "action": "login"}\n{"user": "bob", "action": "upload"}\n'
        parsed_jsonl = parse_jsonl_content(jsonl_str)
        self.assertIn("JSONL Dataset: 2 records total", parsed_jsonl)
        self.assertIn("alice", parsed_jsonl)
        self.assertIn("bob", parsed_jsonl)

    def test_kela_engine_empty_retrieval_does_not_fabricate_sources(self):
        """Verify KelaEngine gracefully reports empty retrieval and emits zero fake sources."""
        import json
        from core.engine import KelaEngine
        from core.provider_manager import BaseInferenceProvider

        class FallbackProvider(BaseInferenceProvider):
            async def chat(self, messages, model=None, options=None):
                return "I do not have specific internal knowledge on that topic."

            async def stream_chat(self, messages, model=None, options=None):
                yield {"token": "I do not have specific internal knowledge on that topic."}
                yield {"done": True}

            async def health_check(self):
                return {"available": True}

        fb_prov = FallbackProvider()
        engine = KelaEngine()

        kb_id = "kb_empty_test"
        create_knowledge_base(name="Empty Test KB", kb_id=kb_id)

        async def run_empty_stream():
            events = []
            async for ev_raw in engine.chat_stream(
                [{"role": "user", "content": "Tell me about quantum gravity in 11 dimensions"}],
                kb_id=kb_id,
            ):
                try:
                    events.append(json.loads(ev_raw.strip()))
                except Exception:
                    pass
            return events

        with patch.object(engine.providers, "get_active_provider", return_value=fb_prov):
            events = asyncio.run(run_empty_stream())

        # Verify NO sources event was emitted (no hallucinated sources!)
        source_events = [e for e in events if e.get("type") == "sources"]
        self.assertEqual(len(source_events), 0, "KELA must never fabricate or invent citations on empty retrieval!")

        # Verify step indicating no matches was emitted
        step_events = [e.get("step", "") for e in events if "step" in e]
        self.assertTrue(any("No relevant information found" in s for s in step_events))

        delete_knowledge_base(kb_id)


if __name__ == "__main__":
    unittest.main()
