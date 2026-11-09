import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from database import initialize_database
from knowledge.chunker import chunk_text
from knowledge.embeddings import cosine_similarity, generate_local_embedding
from knowledge.engine import (
    delete_indexed_document,
    index_directory,
    index_file,
    list_indexed_documents,
    search_knowledge_base,
)
from knowledge.parser import parse_csv_content, parse_file


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
            tmp_path.write_text("# Nexus AI Architecture\n\nNexus AI is an autonomous personal AI operating system.\nIt provides deep research, coding agent, and memory.", encoding="utf-8")

            # 1. Index file
            res1 = index_file(tmp_path)
            self.assertEqual(res1["status"], "indexed")
            doc_id = res1["document_id"]

            # 2. Re-indexing unchanged file should be skipped
            res2 = index_file(tmp_path)
            self.assertEqual(res2["status"], "skipped")
            self.assertEqual(res2["reason"], "unchanged")

            # 3. Search query matching indexed content
            search_results = search_knowledge_base("autonomous personal operating system", top_k=3)
            self.assertGreater(len(search_results), 0)
            self.assertEqual(search_results[0]["title"], "notes.md")
            self.assertIn("Nexus AI", search_results[0]["content"])

            # 4. Delete document
            deleted = delete_indexed_document(doc_id)
            self.assertTrue(deleted)

            # 5. Search after deletion
            after_search = search_knowledge_base("autonomous personal operating system", top_k=3)
            matching = [r for r in after_search if r["document_id"] == doc_id]
            self.assertEqual(len(matching), 0)


if __name__ == "__main__":
    unittest.main()
