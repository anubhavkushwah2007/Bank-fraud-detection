"""
tests/conftest.py (root)
────────────────────────
Pytest configuration for root workspace.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = ROOT / "fraud-investigation-agent"
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

os.environ["OFFLINE_DEV"] = "true"
os.environ["STRICT_GRAPH"] = "false"

from config import settings
settings.OFFLINE_DEV = True
settings.STRICT_GRAPH = False
