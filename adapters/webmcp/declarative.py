"""Declarative WebMCP forms.

Reads ``<form toolname tooldescription>`` annotations from the WebMCP
declarative API and submits the form. This is the HTML tool surface, not
``document.modelContext.registerTool``.

Imperative WebMCP execution needs a Chromium document with WebMCP enabled
(``chrome://flags/#enable-webmcp-testing``). This module does not start a
browser and must not be reported as that check.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PACKAGES = os.path.join(_REPO_ROOT, "packages")
for _p in (_PACKAGES, os.path.join(_PACKAGES, "capability-registry")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from capability import Capability
from mcp_adapter import ExecutionResult


class DeclarativeWebMCPClient:
    """Discover form tools on a page and submit them."""

    def __init__(self, page_url: str, provider: str = "webmcp-page", timeout: float = 5.0) -> None:
        self.page_url = page_url
        self.provider = provider
        self.timeout = timeout
        self._capabilities: Dict[str, Capability] = {}
        self._forms: Dict[str, Dict[str, Any]] = {}

    def discover(self) -> List[Capability]:
        req = urllib.request.Request(self.page_url, method="GET", headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            html = resp.read().decode("utf-8")
        forms = _FormToolParser().parse(html)
        self._capabilities.clear()
        self._forms.clear()
        for form in forms:
            cap_id = f"webmcp.{form['toolname']}"
            action = urllib.parse.urljoin(self.page_url, form.get("action") or self.page_url)
            goals = [g for g in (form.get("data-intent-goals") or "").split(",") if g]
            binds: Dict[str, int] = {}
            for item in (form.get("data-binds") or "").split(","):
                if "=" not in item:
                    continue
                arg, stage = item.split("=", 1)
                binds[arg.strip()] = int(stage.strip())
            metadata: Dict[str, Any] = {
                "specification": "webmcp-declarative-form",
                "imperative_model_context": False,
                "toolname": form["toolname"],
                "method": (form.get("method") or "get").lower(),
                "action": action,
            }
            if goals:
                metadata["intent_goals"] = goals
            if form.get("data-stage"):
                metadata["stage"] = int(form["data-stage"])
            if binds:
                metadata["binds"] = binds
            permissions = [p for p in (form.get("data-permissions") or "web:access").split(",") if p]
            cap = Capability(
                id=cap_id,
                name=form["toolname"],
                description=form["tooldescription"],
                domain=form.get("data-domain") or "web",
                inputs=form["inputs"],
                permissions=permissions,
                provider=self.provider,
                protocol="webmcp",
                endpoint=action,
                metadata=metadata,
            )
            self._capabilities[cap_id] = cap
            self._forms[cap_id] = form
            self._forms[form["toolname"]] = form
        return list(self._capabilities.values())

    def invoke(self, capability_id: str, arguments: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        cap = self._capabilities.get(capability_id)
        if cap is None and f"webmcp.{capability_id}" in self._capabilities:
            cap = self._capabilities[f"webmcp.{capability_id}"]
        if cap is None:
            raise KeyError(f"declarative WebMCP tool not found: {capability_id}")
        action = cap.metadata["action"]
        method = cap.metadata["method"]
        fields = {key: _form_value(value) for key, value in (arguments or {}).items()}
        start = time.perf_counter()
        try:
            if method == "post":
                data = urllib.parse.urlencode(fields).encode("utf-8")
                req = urllib.request.Request(
                    action,
                    data=data,
                    method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                )
            else:
                query = urllib.parse.urlencode(fields)
                joiner = "&" if "?" in action else "?"
                req = urllib.request.Request(action + joiner + query, method="GET", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                content_type = resp.headers.get("Content-Type", "")
            if "json" in content_type or raw[:1] in ("{", "["):
                result: Any = json.loads(raw)
            else:
                result = raw
            success = True
            error = None
        except Exception as exc:
            result = None
            success = False
            error = f"declarative form submit failed: {exc}"
        exec_res = ExecutionResult(
            tool_name=cap.id,
            capability_id=cap.id,
            success=success,
            result=result,
            error=error,
            duration_ms=(time.perf_counter() - start) * 1000.0,
        )
        return exec_res


class _FormToolParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.forms: List[Dict[str, Any]] = []
        self._current: Optional[Dict[str, Any]] = None

    def parse(self, html: str) -> List[Dict[str, Any]]:
        self.feed(html)
        return self.forms

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attr = {key.lower(): value for key, value in attrs}
        if tag == "form" and attr.get("toolname") and attr.get("tooldescription"):
            self._current = {
                "toolname": attr["toolname"],
                "tooldescription": attr["tooldescription"],
                "action": attr.get("action") or "",
                "method": attr.get("method") or "get",
                "data-intent-goals": attr.get("data-intent-goals") or "",
                "data-stage": attr.get("data-stage") or "",
                "data-binds": attr.get("data-binds") or "",
                "data-domain": attr.get("data-domain") or "",
                "data-permissions": attr.get("data-permissions") or "",
                "inputs": {},
            }
            return
        if self._current is None or tag not in ("input", "textarea", "select"):
            return
        name = attr.get("name")
        if not name:
            return
        self._current["inputs"][name] = {
            "type": attr.get("type") or "string",
            "required": "required" in attr,
            "description": attr.get("toolparamdescription") or "",
        }

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


def _form_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value)
