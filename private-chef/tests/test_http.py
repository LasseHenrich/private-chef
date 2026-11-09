"""Exercise actual HTTP parsing without sockets (the coding sandbox disallows bind)."""

import io
import tempfile
import unittest
from pathlib import Path

from test_agent import FakeModel, answer

from private_chef.agent import Chef
from private_chef.config import Settings
from private_chef.server import Application, handler_for
from private_chef.store import Store


class FakeSocket:
    def __init__(self, request):
        self.input = io.BytesIO(request)
        self.output = bytearray()

    def makefile(self, mode, buffering=None):
        return self.input

    def sendall(self, value):
        self.output.extend(value)

    def settimeout(self, timeout):
        pass


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        settings = Settings(Path(self.temp.name) / "chef.db", "a" * 40, "", "test")
        store = Store(settings.db_path)
        store.initialize()
        self.handler = handler_for(Application(settings, Chef(store, FakeModel([answer("Hi")]))))
        self.auth = f"Authorization: Bearer {settings.api_token}\r\n".encode()

    def request(self, wire):
        socket = FakeSocket(wire)
        self.handler(socket, ("127.0.0.1", 9999), None)
        return bytes(socket.output)

    def test_http_health_headers(self):
        result = self.request(b"GET /health HTTP/1.0\r\n\r\n")
        self.assertIn(b"200 OK", result)
        self.assertIn(b"Cache-Control: no-store", result)
        self.assertIn(b'{"status": "ok"}', result)

    def test_http_authentication_before_body_parsing(self):
        result = self.request(b"POST /v1/chat HTTP/1.0\r\nContent-Length: 100\r\n\r\n")
        self.assertIn(b"401 Unauthorized", result)

    def test_http_bad_json_and_size_limits(self):
        prefix = b"POST /v1/chat HTTP/1.0\r\n" + self.auth + b"Content-Type: application/json\r\n"
        self.assertIn(b"400 Bad Request", self.request(prefix + b"Content-Length: 1\r\n\r\n{"))
        self.assertIn(b"413", self.request(prefix + b"Content-Length: 999999\r\n\r\n"))
        self.assertIn(b"400", self.request(prefix + b"Transfer-Encoding: chunked\r\n\r\n"))

    def test_http_authenticated_round_trip(self):
        body = b'{"member_id":"person-1","message":"Hi","request_id":"r1"}'
        headers = (
            b"POST /v1/chat HTTP/1.0\r\n"
            + self.auth
            + b"Content-Type: application/json\r\nContent-Length: "
            + str(len(body)).encode()
        )
        result = self.request(headers + b"\r\n\r\n" + body)
        self.assertIn(b"200 OK", result)
        self.assertIn(b'"reply": "Hi"', result)


if __name__ == "__main__":
    unittest.main()
