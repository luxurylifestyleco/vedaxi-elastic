"""Make sibling Elastic Web packages importable when running pytest.

The elastic-bench package depends on ``intent_ir``, ``capability``,
``factory``/``retriever``, and the demo-bank ``bank``/``manifest`` modules
which live in sibling package directories. This conftest adds those
directories to ``sys.path`` so the tests can import them directly,
matching how the other packages run.
"""

from __future__ import annotations

import os
import sys

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APPS = os.path.join(os.path.dirname(_PACKAGES), "apps")

for _name in (
    "intent-ir",
    "capability-registry",
    "capability-retrieval",
):
    _path = os.path.join(_PACKAGES, _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)

_demo_bank = os.path.join(_APPS, "demo-bank")
if _demo_bank not in sys.path:
    sys.path.insert(0, _demo_bank)
