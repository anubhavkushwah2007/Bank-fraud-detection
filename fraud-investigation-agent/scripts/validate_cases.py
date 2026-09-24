

"""
fraud-investigation-agent/scripts/validate_cases.py
───────────────────────────────────────────────────
Redirects or executes validation script for cases/.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
target_script = ROOT / "scripts" / "validate_cases.py"
if target_script.exists():
    sys.exit(subprocess.call([sys.executable, str(target_script)] + sys.argv[1:]))
else:
    # Direct import/execution if standalone
    pass
