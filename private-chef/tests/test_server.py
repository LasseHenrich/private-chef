import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_agent import FakeModel, answer

from private_chef.agent import Chef
from private_chef.config import Settings, read_env
from private_chef.server import Application
from private_chef.store import Store


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.settings = Settings(
            self.path / "chef.db", "a" * 40, "", "test", whatsapp=("+491111111111", "+492222222222")
        )
        self.store = Store(self.settings.db_path)
        self.store.initialize()
        self.app = Application(self.settings, Chef(self.store, FakeModel([answer("Hello")])))
        self.auth = f"Bearer {self.settings.api_token}"

    def test_health_is_public_but_state_and_mutations_require_token(self):
        self.assertEqual(self.app.dispatch("GET", "/health", "", {})[0], 200)
        for method, path in [("GET", "/v1/state"), ("POST", "/v1/chat"), ("POST", "/v1/tool")]:
            self.assertEqual(self.app.dispatch(method, path, "", {})[0], 401)

    def test_whatsapp_sender_is_mapped_from_allowlist_not_message_arguments(self):
        body = dict(source="whatsapp", sender_id="+492222222222", message="Hello", request_id="r1")
        self.assertEqual(self.app.dispatch("POST", "/v1/chat", self.auth, body)[0], 200)
        self.assertEqual(len(self.store.messages("person-2")), 2)
        self.assertEqual(len(self.store.messages("person-1")), 0)
        body["member_id"] = "person-1"
        self.assertEqual(self.app.dispatch("POST", "/v1/chat", self.auth, body)[0], 400)

    def test_unknown_sender_is_denied(self):
        status, _ = self.app.dispatch(
            "POST",
            "/v1/chat",
            self.auth,
            dict(source="whatsapp", sender_id="+493333333333", message="Hi", request_id="r2"),
        )
        self.assertEqual(status, 403)

    def test_malformed_input_is_rejected(self):
        for body in (
            [],
            {},
            {"member_id": "person-1", "message": "", "request_id": "r3"},
            {"member_id": "person-1", "message": "x" * 4001, "request_id": "r3"},
            {"member_id": "person-1", "message": "Hi", "request_id": "r3", "extra": "x"},
        ):
            with self.subTest(body=type(body)):
                self.assertEqual(self.app.dispatch("POST", "/v1/chat", self.auth, body)[0], 400)

    def test_structured_tools_work_without_a_model_key(self):
        status, body = self.app.dispatch(
            "POST",
            "/v1/tool",
            self.auth,
            dict(
                member_id="person-1",
                name="add_shopping_item",
                arguments=dict(name="rice", quantity=200, unit="g"),
            ),
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["result"][0]["quantity"], 200)
        status, state = self.app.dispatch("GET", "/v1/state", self.auth, {})
        self.assertEqual(status, 200)
        self.assertEqual(state["shopping"][0]["name"], "rice")

    def test_configuration_rejects_duplicate_identities_and_empty_token(self):
        with self.assertRaises(ValueError):
            Settings(self.settings.db_path, "", "", "test").validate_server()
        with self.assertRaises(ValueError):
            Settings(
                self.settings.db_path, "x" * 32, "", "test", whatsapp=("+49123", "+49123")
            ).validate_server()

    def test_env_is_data_not_shell_code(self):
        path = self.path / ".env"
        path.write_text("OPENAI_API_KEY='$(do-not-run)'\nCHEF_PORT=9000\n")
        self.assertEqual(read_env(path)["OPENAI_API_KEY"], "$(do-not-run)")
        with patch.dict("os.environ", {"CHEF_PORT": "9999"}, clear=True):
            self.assertEqual(Settings.load(self.path).port, 9999)


if __name__ == "__main__":
    unittest.main()
