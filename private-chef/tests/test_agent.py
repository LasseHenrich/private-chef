import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from private_chef.agent import Chef, OpenAIResponses
from private_chef.config import Settings
from private_chef.seed import seed
from private_chef.store import Store
from private_chef.validation import ChefError


def answer(text="Done"):
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
    }


def call(name, arguments, call_id="c1"):
    return {
        "output": [
            {
                "type": "function_call",
                "name": name,
                "call_id": call_id,
                "arguments": json.dumps(arguments),
            }
        ]
    }


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.inputs = []

    def create(self, messages, tools):
        self.inputs.append(json.loads(json.dumps(messages)))
        return next(self.responses)


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "chef.db")
        self.store.initialize()
        seed(self.store)

    def test_real_tool_loop_saves_and_replays_response_without_new_model_call(self):
        model = FakeModel(
            [
                call("set_preference", dict(kind="like", value="lentils", remove=False)),
                answer("Saved your preference"),
            ]
        )
        chef = Chef(self.store, model)
        self.assertEqual(chef.chat("person-2", "I like lentils", "r1"), "Saved your preference")
        self.assertEqual(chef.chat("person-2", "I like lentils", "r1"), "Saved your preference")
        self.assertEqual(len(model.inputs), 2)
        self.assertIn("function_call_output", [item.get("type") for item in model.inputs[1]])
        self.assertEqual(self.store.household()["members"][1]["preferences"][0]["value"], "lentils")

    def test_tool_errors_are_returned_to_model_and_cannot_spoof_actor(self):
        model = FakeModel(
            [
                call(
                    "set_preference",
                    dict(kind="like", value="lentils", remove=False, member_id="person-2"),
                ),
                answer("Please retry"),
            ]
        )
        Chef(self.store, model).chat("person-1", "test", "r2")
        self.assertIn("error", json.loads(model.inputs[1][-1]["output"]))
        self.assertEqual(self.store.household()["members"][0]["preferences"], [])

    def test_conversation_history_is_per_person(self):
        model = FakeModel([answer("A"), answer("B"), answer("C")])
        chef = Chef(self.store, model)
        chef.chat("person-1", "personal message one", "r3")
        chef.chat("person-2", "personal message two", "r4")
        chef.chat("person-1", "follow up", "r5")
        self.assertNotIn("personal message one", json.dumps(model.inputs[1]))
        self.assertIn("personal message one", json.dumps(model.inputs[2]))
        self.assertNotIn("personal message two", json.dumps(model.inputs[2]))

    def test_model_cannot_replay_same_tool_call_id(self):
        response = call("add_shopping_item", dict(name="rice", quantity=1, unit="kg"))
        model = FakeModel([response, response])
        with self.assertRaises(ChefError):
            Chef(self.store, model).chat("person-1", "Add rice", "r6")
        self.assertEqual(self.store.shopping()[0]["quantity"], 1)
        with self.assertRaises(ChefError):
            Chef(self.store, model).chat("person-1", "Add rice", "r6")

    def test_empty_answer_fails_safely(self):
        with self.assertRaises(ChefError):
            Chef(self.store, FakeModel([answer("")])).chat("person-1", "hello", "r7")

    def test_missing_key_has_actionable_error(self):
        settings = Settings(self.store.path, "x" * 32, "", "test-model")
        with self.assertRaisesRegex(ChefError, "OPENAI_API_KEY"):
            OpenAIResponses(settings).create([], [])

    def test_provider_payload_and_error_sanitization(self):
        settings = Settings(self.store.path, "x" * 32, "test-secret-never-print", "test-model")
        client = OpenAIResponses(settings)
        with patch("private_chef.agent.urlopen") as request:
            request.return_value.__enter__.return_value.read.return_value = json.dumps(
                answer()
            ).encode()
            client.create([{"role": "user", "content": "Hello"}], [])
            payload = json.loads(request.call_args.args[0].data)
            self.assertFalse(payload["store"])
            self.assertFalse(payload["parallel_tool_calls"])
            self.assertEqual(payload["model"], "test-model")
        for error in (
            HTTPError("https://api.openai.com", 401, "test-secret-never-print", {}, None),
            URLError("test-secret-never-print"),
        ):
            with (
                self.subTest(error=type(error)),
                patch("private_chef.agent.urlopen", side_effect=error),
            ):
                with self.assertRaises(ChefError) as caught:
                    client.create([], [])
                self.assertNotIn(settings.openai_key, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
