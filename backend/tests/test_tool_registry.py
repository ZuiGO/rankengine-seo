import pytest
from backend.services.agent_tools.tool_registry import ToolSpec, ToolRegistry

def test_tool_registry_registration():
    registry = ToolRegistry()
    
    def dummy_handler():
        return True
        
    spec = ToolSpec(
        name="dummy_tool",
        description="A dummy tool",
        parameters={"type": "object", "properties": {}},
        handler=dummy_handler,
        credit_cost=1.5
    )
    
    registry.register(spec)
    
    retrieved = registry.get_tool("dummy_tool")
    assert retrieved is not None
    assert retrieved.name == "dummy_tool"
    assert retrieved.credit_cost == 1.5
    assert len(registry.get_all_tools()) == 1

def test_tool_registry_missing():
    registry = ToolRegistry()
    assert registry.get_tool("nonexistent") is None
