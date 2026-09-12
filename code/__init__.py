import os
import sys
import importlib.util

# Standard library 'code' module fallback so pdb/pytest work when '.' is on sys.path
_stdlib_dir = os.path.dirname(os.__file__)
_stdlib_code_path = os.path.join(_stdlib_dir, "code.py")
if os.path.exists(_stdlib_code_path):
    try:
        _spec = importlib.util.spec_from_file_location("_stdlib_code", _stdlib_code_path)
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            for _k, _v in _mod.__dict__.items():
                if not _k.startswith("__"):
                    globals()[_k] = _v
    except Exception:
        pass
