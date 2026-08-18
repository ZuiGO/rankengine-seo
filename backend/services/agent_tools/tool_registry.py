from typing import Callable, Any, Optional
from pydantic import BaseModel, Field

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict
    handler: Callable
    requires_checkpoint: bool = False
    credit_cost: float = 0.0

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def get_all_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tools_by_names(self, names: list[str]) -> list[ToolSpec]:
        return [self._tools[n] for n in names if n in self._tools]

# Global singleton
registry = ToolRegistry()
