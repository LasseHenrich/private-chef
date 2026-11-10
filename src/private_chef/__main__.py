"""Local setup, model-free tool testing, HTTP serving, and an interactive chat client."""

import argparse
import json
import os
import secrets
import sys
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

from .agent import Chef, OpenAIResponses
from .config import PROJECT_ROOT, Settings
from .openclaw import configure, launch
from .seed import seed
from .server import Application, serve
from .store import Store
from .tools import Tools
from .validation import ChefError


def setup(root: Path = PROJECT_ROOT):
    path = root / ".env"
    if path.exists():
        print(".env already exists; left unchanged")
    else:
        template_path = root / ".env.example"
        template = (
            template_path.read_text()
            if template_path.exists()
            else files("private_chef").joinpath("env.example").read_text()
        )
        template = template.replace(
            "CHEF_API_TOKEN=\n", f"CHEF_API_TOKEN={secrets.token_urlsafe(32)}\n"
        )
        # O_EXCL and mode 0600 prevent races and accidental world-readable secrets.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            file.write(template)
        print("Created private .env; add your OpenAI key and household names when ready")
    settings = Settings.load(root)
    store = Store(settings.db_path)
    store.initialize(settings.names)
    print(f"Database ready; added {seed(store)} starter recipes")


def main():
    parser = argparse.ArgumentParser(description="Private Chef — local shared cooking assistant")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Create .env and initialize the database without API calls")
    commands.add_parser("serve", help="Start authenticated local HTTP service")
    commands.add_parser("state", help="Print shared records (contains personal information)")
    commands.add_parser(
        "configure-openclaw", help="Generate isolated WhatsApp gateway configuration"
    )
    gateway = commands.add_parser(
        "openclaw", help="Run OpenClaw with the local .env and private state"
    )
    gateway.add_argument("arguments", nargs=argparse.REMAINDER)
    chat = commands.add_parser("chat", help="Interactive local chat using your OpenAI API key")
    chat.add_argument("--member", choices=["person-1", "person-2"], default="person-1")
    tool = commands.add_parser("tool", help="Execute a structured tool locally without a model")
    tool.add_argument("name")
    tool.add_argument("--member", choices=["person-1", "person-2"], default="person-1")
    tool.add_argument(
        "--json", default="{}", help="JSON arguments; keep private data out of shell history"
    )
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup()
            return
        if args.command == "openclaw":
            sys.exit(launch(args.arguments))
        settings = Settings.load()
        if args.command == "configure-openclaw":
            print(f"Created {configure(settings)}")
            return
        store = Store(settings.db_path)
        store.initialize(settings.names)
        if args.command == "tool":
            print(
                json.dumps(
                    Tools(store, args.member).execute(args.name, json.loads(args.json)), indent=2
                )
            )
            return
        chef = Chef(store, OpenAIResponses(settings))
        if args.command == "state":
            print(
                json.dumps(
                    {
                        **store.household(),
                        **store.history(),
                        "recipes": store.recipes(),
                        "shopping": store.shopping(),
                    },
                    indent=2,
                )
            )
        elif args.command == "serve":
            serve(Application(settings, chef))
        elif args.command == "chat":
            print(f"Private Chef · {args.member}. Type /quit to leave; /member switches person.")
            actor = args.member
            while True:
                try:
                    message = input(f"{actor}> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if message == "/quit":
                    break
                if message == "/member":
                    actor = "person-2" if actor == "person-1" else "person-1"
                    continue
                if not message:
                    continue
                if len(message) > 4000:
                    print("Please keep messages to 4000 characters")
                    continue
                try:
                    print(chef.chat(actor, message, str(uuid4())))
                except ChefError as error:
                    print(f"Chef: {error}")
    except (ChefError, ValueError, OSError) as error:
        # Config/file errors contain no credential values; provider errors are sanitized.
        print(f"Private Chef: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
