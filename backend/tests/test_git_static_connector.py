import os
import shutil
import pytest
from pathlib import Path

from backend.services.connectors.git_static_connector import GitStaticConnector

# Use the actual repo root to find the sandbox
REPO_ROOT = Path(__file__).parent.parent.parent
SANDBOX_DIR = REPO_ROOT / "sandbox" / "static-replica"
SANDBOX_PATH = SANDBOX_DIR / "index.html"
BACKUP_PATH = SANDBOX_DIR / "index.html.bak"

@pytest.fixture(autouse=True)
def setup_teardown_sandbox():
    """Setup and teardown the static sandbox file before and after each test."""
    # Create the directory if it doesn't exist
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    
    # Write a baseline file
    baseline_html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Railways - Fluid Controls</title>
    <meta name="description" content="Fluid Controls is a supplier to the railway industry for various control equipment.">
</head>
<body>
    <h1>Railways</h1>
    <img src="/images/railway-system.jpg" />
</body>
</html>"""
    
    with open(SANDBOX_PATH, "w", encoding="utf-8") as f:
        f.write(baseline_html)
        
    yield
    
    # Restore the baseline file after test just in case
    with open(SANDBOX_PATH, "w", encoding="utf-8") as f:
        f.write(baseline_html)


@pytest.mark.asyncio
async def test_apply_title_change():
    connector = GitStaticConnector()
    suggestion = {
        "field_type": "title_tag",
        "suggested_value": "New Optimized Title"
    }
    
    success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)
    assert success
    
    # Verify the value was actually updated
    new_value = await connector.read_field("sandbox", "title_tag", "title")
    assert new_value == "New Optimized Title"


@pytest.mark.asyncio
async def test_apply_alt_text():
    connector = GitStaticConnector()
    suggestion = {
        "field_type": "alt_text",
        "suggested_value": "Railway control systems"
    }
    
    success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)
    assert success
    
    # Verify the value
    new_value = await connector.read_field("sandbox", "alt_text", "img")
    assert new_value == "Railway control systems"


@pytest.mark.asyncio
async def test_rollback_suggestion():
    connector = GitStaticConnector()
    suggestion = {
        "field_type": "h1",
        "suggested_value": "Optimized H1",
        "rollback_value": "Railways"
    }
    
    # Apply first
    success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)
    assert success
    
    # Verify applied
    val = await connector.read_field("sandbox", "h1", "h1")
    assert val == "Optimized H1"
    
    # Rollback
    success, error = await connector.rollback_field(suggestion)
    assert success
    
    # Verify rolled back
    val = await connector.read_field("sandbox", "h1", "h1")
    assert val == "Railways"


@pytest.mark.asyncio
async def test_apply_failure_on_invalid_field():
    connector = GitStaticConnector()
    suggestion = {
        "field_type": "invalid_field_type",
        "suggested_value": "New Value"
    }
    
    success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)
    assert not success
    assert "Unsupported field_type" in error
