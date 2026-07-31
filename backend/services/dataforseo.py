import base64
from typing import Optional
import httpx

from backend.config import settings

BASE_URL = "https://api.dataforseo.com"


def _auth_header() -> dict:
    if not settings.dataforseo_login or not settings.dataforseo_password:
        raise ValueError("DataForSEO credentials not configured")
    token = base64.b64encode(
        f"{settings.dataforseo_login}:{settings.dataforseo_password}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


async def domain_keywords(domain: str, limit: int = 20) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v3/keywords_data/google/keywords_for_site/live",
            headers=_auth_header(),
            json=[{
                "domain": domain,
                "limit": limit,
                "location_name": "United States",
                "language_name": "English",
            }],
            timeout=30,
        )
        data = resp.json()
        tasks = data.get("tasks", [])
        if tasks and tasks[0].get("result"):
            return tasks[0]["result"][0].get("items", [])
        return []


async def backlink_summary(target: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v3/backlinks/summary/live",
            headers=_auth_header(),
            json=[{"target": target}],
            timeout=30,
        )
        data = resp.json()
        tasks = data.get("tasks", [])
        if tasks and tasks[0].get("result"):
            return tasks[0]["result"][0]
        return None


async def onpage_summary(url: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v3/on_page/summary/live",
            headers=_auth_header(),
            json=[{"url": url}],
            timeout=30,
        )
        data = resp.json()
        tasks = data.get("tasks", [])
        if tasks and tasks[0].get("result"):
            return tasks[0]["result"][0]
        return None


async def domain_overview(domain: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{BASE_URL}/v3/domain_analytics/google/overview/live",
            headers=_auth_header(),
            json=[{"domain": domain}],
            timeout=30,
        )
        data = resp.json()
        tasks = data.get("tasks", [])
        if tasks and tasks[0].get("result"):
            return tasks[0]["result"][0]
        return None


async def rank_tracking_keywords(domain: str, keywords: list[str]) -> list[dict]:
    async with httpx.AsyncClient() as client:
        payload = [
            {"domain": domain, "keywords": keywords, "location_name": "United States", "language_name": "English"}
        ]
        resp = await client.post(
            f"{BASE_URL}/v3/rank_tracking/keywords/live",
            headers=_auth_header(),
            json=payload,
            timeout=30,
        )
        data = resp.json()
        tasks = data.get("tasks", [])
        if tasks and tasks[0].get("result"):
            return tasks[0]["result"][0].get("items", [])
        return []


async def fetch_all_insights(domain: str) -> dict:
    insights = {"domain": domain, "keywords": [], "backlinks": None, "onpage": None, "overview": None}
    try:
        insights["keywords"] = await domain_keywords(domain)
    except Exception as e:
        insights["keywords_error"] = str(e)
    try:
        insights["backlinks"] = await backlink_summary(domain)
    except Exception as e:
        insights["backlinks_error"] = str(e)
    try:
        insights["onpage"] = await onpage_summary(f"https://{domain}")
    except Exception as e:
        insights["onpage_error"] = str(e)
    try:
        insights["overview"] = await domain_overview(domain)
    except Exception as e:
        insights["overview_error"] = str(e)
    return insights
