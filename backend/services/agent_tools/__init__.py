from backend.services.agent_tools.tool_registry import ToolSpec, registry

from backend.services.agent_tools.domain_tools import *

# Legacy sandbox/single-page tools (crawl_urls, generate_suggestions, apply_changes, etc.)
# self-register into the registry at the bottom of agent_tools_legacy.py.
import backend.services.agent_tools_legacy  # noqa: F401 – triggers registration

TOOL_REGISTRY = registry._tools

from backend.db.mongo import get_db  # noqa: F401 – re-exported for test monkeypatching
