"""Shared test setup.

Offline tripwire: ALPHAMAXXIN_OFFLINE=1 makes every real data/LLM provider
raise instead of touching the network, so any test that accidentally reaches
past its fixtures fails loudly. This is a hard project rule — development and
testing never call APIs; live runs are done manually by the user.
"""
import os
import sys
from pathlib import Path

os.environ["ALPHAMAXXIN_OFFLINE"] = "1"

# Make `backend.app.*` and `app.*` both importable when pytest runs from backend/.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent
for p in (str(_REPO_ROOT), str(_BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
