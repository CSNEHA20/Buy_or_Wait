"""Make the repository's code directory importable as ``buy_or_wait``."""

import sys
import types
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))
if "buy_or_wait" not in sys.modules:
    package = types.ModuleType("buy_or_wait")
    package.__path__ = [str(CODE_DIR)]
    sys.modules["buy_or_wait"] = package
