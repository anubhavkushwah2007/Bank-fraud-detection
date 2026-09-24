"""
tests/conftest.py
─────────────────
Pytest configuration for fraud investigation agent test suite.
Ensures OFFLINE_DEV is True for fast, deterministic unit test execution.
"""
import os
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Enforce offline dev mode for all test runs
os.environ["OFFLINE_DEV"] = "true"
os.environ["STRICT_GRAPH"] = "false"

from config import settings
settings.OFFLINE_DEV = True
settings.STRICT_GRAPH = False
