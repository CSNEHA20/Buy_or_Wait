
"""Project code package.

The directory is named ``code`` for the challenge contract.  When pytest adds
it directly to ``sys.path`` it can shadow Python's standard-library ``code``
module (which ``pdb`` imports), so expose the standard-library API here too.
"""

from __future__ import annotations

import importlib.util
import sys
import sysconfig
from pathlib import Path

_stdlib_code = Path(sysconfig.get_path("stdlib")) / "code.py"
if not _stdlib_code.exists():
    _stdlib_code = Path(sys.executable).resolve().parent / "code.py"
if not _stdlib_code.exists():
    _stdlib_code = Path(sys.executable).resolve().parent / "Lib" / "code.py"
if not _stdlib_code.exists():
    for _entry in sys.path:
        _candidate = Path(_entry) / "code.py"
        if _candidate.exists():
            _stdlib_code = _candidate
            break
_spec = importlib.util.spec_from_file_location("_stdlib_code", _stdlib_code)
if _spec and _spec.loader:
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    for _name in dir(_module):
        if not _name.startswith("__"):
            globals().setdefault(_name, getattr(_module, _name))
