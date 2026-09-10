"""Make sibling Elastic Web packages importable when running pytest.

The capability-retrieval package depends on ``intent_ir`` and
``capability``/``registry``/``seed`` which live in sibling package
directories. This conftest adds those directories to ``sys.path`` so the
tests can import them directly, matching how the other packages run.
"""

from __future__ import annotations

import os
import sys

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for _name in ("intent-ir", "capability-registry"):
    _path = os.path.join(_PACKAGES, _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)
