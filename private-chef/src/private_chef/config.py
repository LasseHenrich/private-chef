"""Small, non-executing .env reader. Environment variables take precedence."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().replace("_", "").isalnum():
            raise ValueError("Invalid .env entry; expected KEY=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    db_path: Path
    api_token: str
    openai_key: str
    model: str
    host: str = "127.0.0.1"
    port: int = 8787
    names: tuple[str, str] = ("Person 1", "Person 2")
    whatsapp: tuple[str, str] = ("", "")

    @classmethod
    def load(cls, root: Path = PROJECT_ROOT) -> "Settings":
        env = {**read_env(root / ".env"), **os.environ}
        db_path = Path(env.get("CHEF_DB_PATH", "data/chef.sqlite3")).expanduser()
        return cls(
            db_path=db_path if db_path.is_absolute() else root / db_path,
            api_token=env.get("CHEF_API_TOKEN", ""),
            openai_key=env.get("OPENAI_API_KEY", ""),
            model=env.get("OPENAI_MODEL", "gpt-4.1-mini"),
            host=env.get("CHEF_HOST", "127.0.0.1"),
            port=int(env.get("CHEF_PORT", "8787")),
            names=(
                env.get("CHEF_USER_1_NAME", "Person 1"),
                env.get("CHEF_USER_2_NAME", "Person 2"),
            ),
            whatsapp=(env.get("CHEF_USER_1_WHATSAPP", ""), env.get("CHEF_USER_2_WHATSAPP", "")),
        )

    def validate_server(self) -> None:
        if len(self.api_token) < 32:
            raise ValueError("Set CHEF_API_TOKEN to at least 32 characters; run setup first")
        if not 1 <= self.port <= 65535:
            raise ValueError("CHEF_PORT must be between 1 and 65535")
        numbers = [number for number in self.whatsapp if number]
        if len(set(numbers)) != len(numbers):
            raise ValueError("Each household member needs a different WhatsApp number")
        for number in numbers:
            if not re.fullmatch(r"\+[1-9][0-9]{6,14}", number):
                raise ValueError("WhatsApp numbers must use E.164 format, starting with +")
