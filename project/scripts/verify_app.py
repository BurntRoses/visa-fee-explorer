#!/usr/bin/env python3
"""Current workbench acceptance entry; r2 verifier is preserved under legacy/."""
from pathlib import Path
import subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
for name in ['verify_workbench_data.py','verify_workbench_queries.py','verify_workbench_browser.py']:
 subprocess.run([sys.executable,str(ROOT/'scripts'/name)],cwd=ROOT,check=True)
