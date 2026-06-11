"""Backward-compat shim — symbols moved to `scheduler.py`.

`orchestrate.py` loads sibling modules via `_load_sibling`, which uses
`importlib.util.spec_from_file_location` and never executes the parent
package. That means a plain `from .scheduler import ...` won't resolve here.
We replay the same loader pattern to pull scheduler in and re-export the
public names this module used to define.
"""

from __future__ import annotations

import importlib.util as _ilu
import sys as _sys
from pathlib import Path as _Path

_here = _Path(__file__).parent
_key = f"{_here.parent.name}.scheduler"

if _key in _sys.modules:
    _scheduler = _sys.modules[_key]
else:
    _spec = _ilu.spec_from_file_location(_key, _here / "scheduler.py")
    _scheduler = _ilu.module_from_spec(_spec)
    _sys.modules[_key] = _scheduler
    _spec.loader.exec_module(_scheduler)  # type: ignore[union-attr]

Plan = _scheduler.Plan
partition = _scheduler.partition
_topo_sort = _scheduler._topo_sort
_has_downstream_hitl = _scheduler._has_downstream_hitl
