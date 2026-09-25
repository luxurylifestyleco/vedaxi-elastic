"""Import sibling source packages for projection tests."""

import os
import sys

_PACKAGES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _name in (
    "capability-projection",
    "capability-registry",
    "capability-retrieval",
    "intent-ir",
    "recipe-schema",
    "recipe-runtime",
):
    _path = os.path.join(_PACKAGES, _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)
