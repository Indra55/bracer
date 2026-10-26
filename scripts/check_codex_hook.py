"""Ask the installed Codex to discover the global band hook; starts no agent turn."""

import asyncio
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from miband_agent.codex import AppServer


async def check():
    async def notification(_):
        pass

    executable = shutil.which("codex")
    if executable is None:
        raise RuntimeError("Codex is not installed")
    async with AppServer([executable, "app-server", "--listen", "stdio://"], notification) as server:
        result = await server.request("hooks/list", {"cwds": [str(ROOT)]})
    matching = []
    for entry in result.get("data", []):
        for hook in entry.get("hooks", []):
            if "codex_approval_hook.py" in hook.get("command", ""):
                matching.append({key: hook.get(key) for key in
                                 ("eventName", "matcher", "enabled", "sourcePath", "trustStatus")})
    if not matching:
        raise RuntimeError("Installed Codex did not discover the band approval hook")
    print(json.dumps(matching))


if __name__ == "__main__":
    try:
        asyncio.run(check())
    except Exception as error:
        raise SystemExit(f"Codex hook check failed: {error}") from None
