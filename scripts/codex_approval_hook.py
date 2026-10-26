"""Absolute-path entrypoint; works when Codex runs in another project."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from miband_agent.hook import entrypoint


if __name__ == "__main__":
    sys.exit(entrypoint())
