"""Main entrypoint for local development.

Running ``uv run python main.py`` should always load the latest desktop frontend,
so this file forces Tauri dev mode before delegating to the CLI entrypoint.
"""

import os
import sys
from pathlib import Path


project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))


if __name__ == "__main__":
    os.environ.setdefault("MPH_AGENT_TAURI_DEV", "1")

    from cli import main

    main()
