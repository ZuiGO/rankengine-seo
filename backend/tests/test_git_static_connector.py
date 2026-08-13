"""
Tests for GitStaticConnector.
These tests mock the file system and git operations so they run fast
and don't need a real sandbox checkout.
"""
import os
import re
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

from backend.services.connectors.git_static_connector import GitStaticConnector


# ------------------------------------------------------------------
# Helpers / shared fixtures
# ------------------------------------------------------------------

def _make_suggestion(**kwargs):
    base = {
        "id": "test-sug-001",
        "field_type": "title",
        "suggested_value": "New Optimized Title",
        "current_value": "Old Title",
    }
    base.update(kwargs)
    return base


# ------------------------------------------------------------------
# test_apply_field: title
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_title_change():
    """Applying a title change succeeds when regex matches and git/vercel succeed."""
    connector = GitStaticConnector()
    suggestion = _make_suggestion(field_type="title", suggested_value="New Optimized Title")

    with (
        patch.object(connector, "_modify_source_file", return_value=(True, "", "/some/file")),
        patch.object(connector, "_commit_changes", return_value=("abc123", "diff", "")),
        patch.object(connector, "_trigger_vercel_deploy", return_value=(True, "https://vercel.preview")),
        patch("backend.services.connectors.git_static_connector.capture_snapshot", new_callable=AsyncMock),
    ):
        success, error, commit, diff, preview = await connector.apply_field(suggestion)

    assert success, f"Expected success but got error: {error}"
    assert commit == "abc123"
    assert preview == "https://vercel.preview"


# ------------------------------------------------------------------
# test_apply_field: alt_text
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_alt_text():
    """Applying an alt_text suggestion succeeds."""
    connector = GitStaticConnector()
    suggestion = _make_suggestion(field_type="alt_text", suggested_value="Railway control systems")

    with (
        patch.object(connector, "_modify_source_file", return_value=(True, "", "/some/Hero.tsx")),
        patch.object(connector, "_commit_changes", return_value=("def456", "diff", "")),
        patch.object(connector, "_trigger_vercel_deploy", return_value=(True, "https://vercel.preview2")),
        patch("backend.services.connectors.git_static_connector.capture_snapshot", new_callable=AsyncMock),
    ):
        success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)

    assert success, f"Expected success but got error: {error}"


# ------------------------------------------------------------------
# test rollback
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rollback_suggestion():
    """Rollback reverts the commit and reports success."""
    connector = GitStaticConnector()
    suggestion = _make_suggestion(
        field_type="title",
        suggested_value="Optimized Title",
        current_value="Original Title",
    )

    # First: apply
    with (
        patch.object(connector, "_modify_source_file", return_value=(True, "", "/some/file")),
        patch.object(connector, "_commit_changes", return_value=("commit-abc", "diff", "")),
        patch.object(connector, "_trigger_vercel_deploy", return_value=(True, "https://preview-apply")),
        patch("backend.services.connectors.git_static_connector.capture_snapshot", new_callable=AsyncMock),
    ):
        success, error, commit_hash, _diff, _preview = await connector.apply_field(suggestion)

    assert success

    # Now rollback
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "reverted"
    mock_proc.stderr = ""

    with (
        patch("subprocess.run", return_value=mock_proc),
        patch.object(connector, "_trigger_vercel_deploy", return_value=(True, "https://preview-rollback")),
        patch("backend.services.connectors.git_static_connector.capture_snapshot", new_callable=AsyncMock),
    ):
        rb_success, rb_error, _new_commit, _rb_preview = await connector.rollback_field(suggestion, commit_hash)

    assert rb_success, f"Rollback failed: {rb_error}"


# ------------------------------------------------------------------
# test invalid field_type
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_failure_on_invalid_field():
    """Applying an unsupported field_type returns failure."""
    connector = GitStaticConnector()
    suggestion = _make_suggestion(field_type="invalid_field_type", suggested_value="new value")

    # _modify_source_file will be called with the real logic
    # We just need to ensure it hits the else branch
    with (
        patch("backend.services.connectors.git_static_connector.capture_snapshot", new_callable=AsyncMock),
    ):
        success, error, _commit, _diff, _preview = await connector.apply_field(suggestion)

    assert not success
    assert "Unsupported field_type" in error
