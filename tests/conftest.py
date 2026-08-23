"""
Shared pytest fixtures/setup for the whole test suite. Gateway/ is not an
installable package (no setup.py/pyproject.toml, matching the flat module
layout in CLAUDE.md), so its directory is added to sys.path here once,
rather than every test file hacking sys.path individually.
"""

import sys
from pathlib import Path

GATEWAY_DIR = Path(__file__).resolve().parent.parent / "Gateway"
if str(GATEWAY_DIR) not in sys.path:
    sys.path.insert(0, str(GATEWAY_DIR))
