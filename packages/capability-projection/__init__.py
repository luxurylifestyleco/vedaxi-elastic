"""Protocol projections for the canonical Elastic Capability model."""

try:
    from .projection import (
        project,
        to_a2a_skill,
        to_mcp_tool,
        to_ucp_capability,
        to_webmcp_tool,
        UCP_VERSION,
    )
except ImportError:  # source-tree imports used by this repository's tests
    from projection import (
        project,
        to_a2a_skill,
        to_mcp_tool,
        to_ucp_capability,
        to_webmcp_tool,
        UCP_VERSION,
    )

try:
    from .webmcp_boundary import WebMCPBoundary
except ImportError:  # source-tree imports used by this repository's tests
    from webmcp_boundary import WebMCPBoundary

__all__ = [
    "project",
    "to_a2a_skill",
    "to_mcp_tool",
    "to_ucp_capability",
    "to_webmcp_tool",
    "UCP_VERSION",
    "WebMCPBoundary",
]
