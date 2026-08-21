from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


CHECKS = [
    ("Tests", ["pytest"]),
    ("Ruff lint", ["ruff", "check", "."]),
    ("Ruff format", ["ruff", "format", "--check", "."]),
    ("Mypy", ["mypy", "src"]),
]


for name, command in CHECKS:
    print(f"\n{name}: {' '.join(command)}")
    result = subprocess.run(
        [sys.executable, "-m", *command], cwd=PROJECT_ROOT, check=False
    )
    if result.returncode != 0:
        sys.exit(result.returncode)

print("\nAll checks passed.")
