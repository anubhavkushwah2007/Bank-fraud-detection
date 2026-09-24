"""
run_all.py
──────────
Runs all 20 real benchmark cases from case_pack.csv with strict graph validation by default.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cmd_path = ROOT / "eval" / "run_benchmark.py"

strict_flag = ["--strict"] if "--no-strict" not in sys.argv and "--offline" not in sys.argv else []
other_args = [a for a in sys.argv[1:] if a not in ("--no-strict", "--offline")]
cmd = [sys.executable, str(cmd_path)] + strict_flag + (other_args or ["--all"])
sys.exit(subprocess.call(cmd, cwd=str(ROOT)))
