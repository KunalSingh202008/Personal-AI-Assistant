import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

import database
from database import initialize_database
from main import app
from core.permission_manager import permission_manager


class SecurityAndCorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test_sec.db"
        cls.db_patch = patch.object(database, "DATABASE_PATH", cls.db_path)
        cls.db_patch.start()
        initialize_database()
        cls.token = permission_manager.local_token
        cls.unauth_client = TestClient(app)
        cls.auth_client = TestClient(app, headers={"X-KELA-Token": cls.token})

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.temp_dir.cleanup()

    def test_pc_system_unauthorized_without_token(self):
        resp = self.unauth_client.get("/api/pc/system")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("Unauthorized", resp.json()["detail"])

    def test_pc_system_unauthorized_with_invalid_token(self):
        resp = self.unauth_client.get("/api/pc/system", headers={"X-KELA-Token": "invalid_wrong_token"})
        self.assertEqual(resp.status_code, 401)

    def test_pc_system_authorized_with_valid_header(self):
        resp = self.auth_client.get("/api/pc/system")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("metrics", resp.json())

    def test_pc_system_authorized_with_bearer_token(self):
        resp = self.unauth_client.get("/api/pc/system", headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(resp.status_code, 200)

    def test_voice_speak_unauthorized_without_token(self):
        resp = self.unauth_client.post("/api/voice/speak", json={"text": "hello"})
        self.assertEqual(resp.status_code, 401)

    def test_anti_dns_rebinding_rejects_evil_host(self):
        resp = self.auth_client.get("/api/pc/system", headers={"Host": "evil-attacker.com"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("DNS rebinding", resp.json()["detail"])

    def test_anti_dns_rebinding_allows_loopback_hosts(self):
        for valid_host in ["localhost:8001", "127.0.0.1:8001", "localhost", "127.0.0.1"]:
            resp = self.auth_client.get("/api/pc/system", headers={"Host": valid_host})
            self.assertEqual(resp.status_code, 200)

    def test_untrusted_origin_rejected(self):
        resp = self.auth_client.get("/api/pc/system", headers={"Origin": "https://malicious-site.com"})
        self.assertEqual(resp.status_code, 403)
        self.assertIn("Origin not authorized", resp.json()["detail"])

    def test_trusted_origin_accepted(self):
        for origin in ["http://localhost:5173", "http://127.0.0.1:5175"]:
            resp = self.auth_client.get("/api/pc/system", headers={"Origin": origin})
            self.assertEqual(resp.status_code, 200)

    def test_auth_local_token_endpoint(self):
        # Must return valid token to loopback client
        resp = self.unauth_client.get("/api/auth/local-token")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("token", data)
        self.assertEqual(data["token"], self.token)

    def test_auth_local_token_rejects_untrusted_host(self):
        resp = self.unauth_client.get("/api/auth/local-token", headers={"Host": "evil.com"})
        self.assertEqual(resp.status_code, 403)

    def test_providers_endpoint(self):
        resp = self.unauth_client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("active_provider", data)
        self.assertIn("providers", data)

    def test_providers_select_endpoint(self):
        # Valid selection
        resp = self.unauth_client.post("/api/providers/select", json={"provider": "cloud"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["active_provider"], "cloud")

        # Invalid selection
        resp2 = self.unauth_client.post("/api/providers/select", json={"provider": "unknown_ai"})
        self.assertEqual(resp2.status_code, 400)

        # Restore default
        self.unauth_client.post("/api/providers/select", json={"provider": "ollama"})


if __name__ == "__main__":
    unittest.main()
