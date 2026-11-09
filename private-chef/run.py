"""Run from a checkout without installing packages or downloading dependencies."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from private_chef.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
