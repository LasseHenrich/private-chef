"""Generate an isolated, local OpenClaw configuration and forward its CLI safely."""

import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

from .config import PROJECT_ROOT, Settings, read_env
from .validation import ChefError


def configure(settings: Settings, root: Path = PROJECT_ROOT) -> Path:
    settings.validate_server()
    if not all(settings.whatsapp):
        raise ChefError("Set both CHEF_USER_1_WHATSAPP and CHEF_USER_2_WHATSAPP in .env first")
    if not (root / "openclaw" / "openclaw.plugin.json").is_file():
        raise ChefError(
            "WhatsApp setup needs the repository's openclaw/ adapter; run from the checkout"
        )
    state = root / "data" / "openclaw"
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = state / "openclaw.json"
    if path.exists():
        raise ChefError("OpenClaw config already exists. Edit it in data/openclaw/openclaw.json")
    config = {
        "gateway": {
            "mode": "local",
            "bind": "loopback",
            "auth": {"mode": "token", "token": secrets.token_urlsafe(32)},
        },
        "agents": {
            "defaults": {
                "workspace": str(state / "workspace"),
                "model": {"primary": "openai/" + settings.model},
            }
        },
        "session": {"dmScope": "per-channel-peer"},
        "channels": {
            "whatsapp": {
                "dmPolicy": "allowlist",
                "allowFrom": list(settings.whatsapp),
                "groupPolicy": "disabled",
                "configWrites": False,
            }
        },
        "plugins": {
            "allow": ["private-chef", "whatsapp"],
            "load": {"paths": [str(root / "openclaw")]},
            "entries": {
                "private-chef": {"enabled": True, "config": {"naturalLanguageTool": False}}
            },
        },
        # /chef bypasses the main agent, so ordinary WhatsApp text needs no general tools.
        "tools": {"profile": "messaging"},
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        json.dump(config, file, indent=2)
        file.write("\n")
    return path


def launch(arguments: list[str], root: Path = PROJECT_ROOT) -> int:
    executable = shutil.which("openclaw")
    if not executable:
        raise ChefError("OpenClaw is not installed. Follow docs/openclaw.md, then retry")
    state = root / "data" / "openclaw"
    config = state / "openclaw.json"
    if not config.exists():
        raise ChefError("Run configure-openclaw after setting your WhatsApp numbers")
    env = {**read_env(root / ".env"), **os.environ}
    env["OPENCLAW_STATE_DIR"] = str(state)
    env["OPENCLAW_CONFIG_PATH"] = str(config)
    return subprocess.run([executable, *arguments], env=env, check=False).returncode
