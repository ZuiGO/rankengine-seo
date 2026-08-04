"""Competitor gap analysis using DataForSEO.

Compares the user's target site against named competitors on keywords and
backlinks, surfacing gaps (competitor keywords the user doesn't rank for,
competitor backlink sources the user lacks).
"""

from backend.services.dataforseo import domain_keywords, backlink_referring_domains


def _normalize_keyword(kw: str) -> str:
    return " ".join(kw.strip().lower().split())


async def competitor_gap(target: str, competitors: list[str], limit: int = 50) -> dict:
    target_kw = {_normalize_keyword(k.get("keyword", "")) for k in await domain_keywords(target, limit)}
    target_domains = {d.get("source_domain", "") for d in await backlink_referring_domains(target, limit)}

    per_competitor = []
    for comp in competitors:
        entry = {"competitor": comp, "error": None}
        try:
            comp_kw = {_normalize_keyword(k.get("keyword", "")) for k in await domain_keywords(comp, limit)}
            comp_domains = {d.get("source_domain", "") for d in await backlink_referring_domains(comp, limit)}
            entry["keyword_gaps"] = sorted(comp_kw - target_kw)[:20]
            entry["keyword_overlap"] = len(comp_kw & target_kw)
            entry["backlink_gaps"] = sorted(comp_domains - target_domains)[:20]
            entry["shared_backlinks"] = len(comp_domains & target_domains)
        except Exception as e:
            entry["error"] = str(e)
        per_competitor.append(entry)

    return {
        "target": target,
        "competitors": per_competitor,
        "source": "dataforseo",
    }