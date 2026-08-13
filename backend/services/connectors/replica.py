"""Replica connector - applies suggestions to the staging replica."""

from typing import Any

from backend.services.connectors.base import BaseConnector
from backend.services.staging import (
    apply_override,
    get_overrides_for_page,
    render_staging_page,
)


class ReplicaConnector(BaseConnector):
    """Connector that writes to the staging replica store and verifies by re-rendering."""

    async def apply_field(self, suggestion: dict[str, Any]) -> tuple[bool, str]:
        """Write suggestion to staging overrides store."""
        try:
            staging_page_id = suggestion.get("staging_page_id")
            if not staging_page_id:
                return False, "No staging_page_id in suggestion"

            field_type = suggestion.get("field_type")
            value = suggestion.get("suggested_value")
            suggestion_id = suggestion.get("_id") or suggestion.get("id")

            if not all([field_type, value, suggestion_id]):
                return False, "Missing required fields"

            from backend.services.staging import apply_override
            await apply_override(staging_page_id, field_type, value, suggestion_id)
            return True, ""
        except Exception as e:
            return False, str(e)

    async def read_field(self, page_url: str, field_type: str, selector: str) -> str:
        """Re-read the field from the rendered staging page."""
        # Find the staging page by URL
        from backend.db.mongo import get_db
        from bson import ObjectId
        from bs4 import BeautifulSoup

        db = get_db()
        page = await db.staging_pages.find_one({"url": page_url})
        if not page:
            return ""

        staging_page_id = str(page["_id"])
        overrides = await self._get_overrides(staging_page_id)
        html = await render_staging_page(staging_page_id, overrides)

        soup = BeautifulSoup(html, "lxml")
        return self._extract_field(soup, field_type, selector)

    async def rollback_field(self, suggestion: dict[str, Any]) -> tuple[bool, str]:
        """Rollback to the previous value."""
        try:
            staging_page_id = suggestion.get("staging_page_id")
            field_type = suggestion.get("field_type")
            rollback_value = suggestion.get("rollback_value")
            suggestion_id = suggestion.get("_id") or suggestion.get("id")

            if not all([staging_page_id, field_type, rollback_value, suggestion_id]):
                return False, "Missing required fields for rollback"

            from backend.services.staging import apply_override
            await apply_override(staging_page_id, field_type, rollback_value, suggestion_id)
            return True, ""
        except Exception as e:
            return False, str(e)

    async def _get_overrides(self, staging_page_id: str) -> dict[str, str]:
        from backend.services.staging import get_overrides_for_page
        return await get_overrides_for_page(staging_page_id)

    def _extract_field(self, soup, field_type: str, selector: str) -> str:
        """Extract a field value from the rendered HTML."""
        if field_type == "title_tag":
            el = soup.find("title")
            return el.get_text(strip=True) if el else ""
        elif field_type == "meta_description":
            el = soup.find("meta", attrs={"name": "description"})
            return el.get("content", "").strip() if el else ""
        elif field_type == "h1":
            el = soup.find("h1")
            return el.get_text(strip=True) if el else ""
        elif field_type == "meta_description":
            el = soup.find("meta", attrs={"name": "description"})
            return el.get("content", "").strip() if el else ""
        # For other fields, try the selector
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else ""