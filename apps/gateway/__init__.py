"""Elastic Web HTTP API gateway.

A thin HTTP layer over the Elastic Web foundation packages. All business
logic lives in the packages under ``packages/`` and the ``demo-bank`` app;
this module only wires HTTP requests to package functions.
"""

from __future__ import annotations

__version__ = "0.1.0"
