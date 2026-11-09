"""Authenticated loopback HTTP API for local development and the OpenClaw adapter."""

import hmac
import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .agent import Chef
from .config import Settings
from .tools import Tools, definitions
from .validation import ChefError

LOGGER = logging.getLogger(__name__)
MAX_BODY = 32000


class Application:
    """Transport-independent routes, also testable without binding a socket."""

    def __init__(self, settings: Settings, chef: Chef):
        settings.validate_server()
        self.settings, self.chef = settings, chef
        self.slots = threading.BoundedSemaphore(4)

    def authorize(self, authorization: str) -> bool:
        return hmac.compare_digest(authorization.encode(),
                                   f"Bearer {self.settings.api_token}".encode())

    def actor(self, body: dict) -> str:
        if body.get("source", "local") == "whatsapp":
            if "member_id" in body:
                raise ChefError("WhatsApp identity must come from sender metadata")
            sender = body.get("sender_id")
            for member_id, number in zip(("person-1", "person-2"), self.settings.whatsapp, strict=True):
                if number and sender == number:
                    return member_id
            raise PermissionError("Sender is not in the household allowlist")
        if body.get("source", "local") != "local" or "sender_id" in body:
            raise ChefError("Invalid message source")
        actor = body.get("member_id")
        if actor not in {"person-1", "person-2"}:
            raise ChefError("Choose member_id person-1 or person-2")
        return actor

    def dispatch(self, method: str, path: str, authorization: str, body: dict) -> tuple[int, dict]:
        if method == "GET" and path == "/health":
            return 200, {"status": "ok"}
        if not self.authorize(authorization):
            return 401, {"error": "Authentication required"}
        try:
            if method == "GET" and path == "/v1/state":
                with self.chef.lock:
                    store = self.chef.store
                    return 200, {**store.household(), **store.history(),
                                 "recipes": store.recipes(), "shopping": store.shopping()}
            if method == "GET" and path == "/v1/tools":
                return 200, {"tools": definitions()}
            if method != "POST" or path not in {"/v1/chat", "/v1/tool"}:
                return 404, {"error": "Not found"}
            if not isinstance(body, dict):
                raise ChefError("Expected a JSON object")
            allowed = {"member_id", "source", "sender_id"}
            allowed |= {"message", "request_id"} if path == "/v1/chat" else {"name", "arguments"}
            if set(body) - allowed:
                raise ChefError("Unknown request fields")
            actor = self.actor(body)
            if path == "/v1/tool":
                name = body.get("name")
                if not isinstance(name, str):
                    raise ChefError("Tool name must be a string")
                with self.chef.lock:
                    result = Tools(self.chef.store, actor).execute(name, body.get("arguments", {}))
                return 200, {"result": result}
            message, request_id = body.get("message"), body.get("request_id")
            if not isinstance(message, str) or not 1 <= len(message.strip()) <= 4000:
                raise ChefError("message must contain 1–4000 characters")
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                raise ChefError("A request_id of 1–128 characters is required")
            if not self.slots.acquire(blocking=False):
                return 429, {"error": "Chef is busy; try again shortly"}
            try:
                reply = self.chef.chat(actor, message, request_id)
                return 200, {"reply": reply, "request_id": request_id}
            finally:
                self.slots.release()
        except PermissionError:
            return 403, {"error": "Sender is not in the household allowlist"}
        except ChefError as error:
            return 400, {"error": str(error)}
        except Exception:
            # No exception text or tracebacks: those may contain messages or credentials.
            LOGGER.error("Request failed; check database availability and configuration")
            return 500, {"error": "Request failed. Some changes may have been saved; check current state"}


def handler_for(application: Application):
    class Handler(BaseHTTPRequestHandler):
        server_version = "PrivateChef"
        sys_version = ""

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, format, *args):
            # Access logs can contain phone numbers, chat text or tokens in URLs.
            return

        def send_json(self, status: int, payload: dict):
            data = json.dumps(payload, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            status, result = application.dispatch("GET", self.path,
                                                   self.headers.get("Authorization", ""), {})
            self.send_json(status, result)

        def do_POST(self):
            if not application.authorize(self.headers.get("Authorization", "")):
                self.close_connection = True
                self.send_json(401, {"error": "Authentication required"})
                return
            if self.headers.get_content_type() != "application/json":
                self.close_connection = True
                self.send_json(415, {"error": "Use application/json"})
                return
            try:
                if self.headers.get("Transfer-Encoding"):
                    raise ChefError("Transfer encoding is not supported")
                raw_length = self.headers.get("Content-Length", "")
                if not raw_length.isdigit() or len(raw_length) > 8:
                    raise ChefError("A valid Content-Length is required")
                length = int(raw_length)
                if not 0 < length <= MAX_BODY:
                    self.close_connection = True
                    self.send_json(413, {"error": "Request is too large or empty"})
                    return
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ChefError("Incomplete request")
                body = json.loads(raw)
            except (ValueError, UnicodeError, ChefError, socket.timeout):
                self.close_connection = True
                self.send_json(400, {"error": "Invalid JSON request"})
                return
            status, result = application.dispatch("POST", self.path,
                                                   self.headers.get("Authorization", ""), body)
            self.send_json(status, result)

    return Handler


def serve(application: Application):
    if application.settings.host not in {"127.0.0.1", "localhost"}:
        raise ChefError("Local server must bind to loopback. Use a hardened deployment adapter later")
    with ThreadingHTTPServer((application.settings.host, application.settings.port),
                             handler_for(application)) as server:
        print(f"Private Chef listening on http://{application.settings.host}:{application.settings.port}")
        print("Press Ctrl+C to stop. Chat is available once OPENAI_API_KEY is configured.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped")
