"""
run_all.py
──────────
Runs all 20 real benchmark cases from case_pack.csv with strict graph validation by default.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AGENT_DIR = ROOT / "fraud-investigation-agent" if (ROOT / "fraud-investigation-agent").exists() else ROOT

strict_flag = ["--strict"] if "--no-strict" not in sys.argv and "--offline" not in sys.argv else []
other_args = [a for a in sys.argv[1:] if a not in ("--no-strict", "--offline")]
cmd = [sys.executable, str(AGENT_DIR / "eval" / "run_benchmark.py")] + strict_flag + (other_args or ["--all"])
sys.exit(subprocess.call(cmd, cwd=str(AGENT_DIR)))
