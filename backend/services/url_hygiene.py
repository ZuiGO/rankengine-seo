"""URL-hygiene / crawl-budget audit (offline, crawl-derived).

Checks the crawled URL inventory for faceted/parameterized URLs, path
readability (lowercase, hyphens, slug length), trailing-slash consistency,
and locale-parameter usage — the measurable parts of the seo-audit skill's
"URL Structure" and "Crawl Budget" checklists.
"""

from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

from backend.db.mongo import get_db
from backend.logging_setup import get_logger

logger = get_logger("url_hygiene")

FACET_PARAMS = {
    "page", "p", "pg", "category", "cat", "tag", "brand", "size", "color",
    "colour", "sort", "order", "filter", "facet", "view", "currency", "lang",
    "locale", "price", "rating", "material",
}

MAX_SLUG_LENGTH = 75


async def audit_url_hygiene(job_id: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"url": 1}).to_list(length=None)

    param_counter: Counter[str] = Counter()
    param_pages = 0
    facet_pages = 0
    uppercase_paths = 0
    underscore_paths = 0
    long_slugs = 0
    slash_pages = 0
    no_slash_pages = 0
    lang_param_pages = 0
    param_samples: dict[str, list[str]] = {}

    for p in pages:
        url = p.get("url") or ""
        parsed = urlparse(url)
        query = parsed.query or ""
        if query:
            param_pages += 1
            names = {pair.split("=", 1)[0].lower() for pair in query.split("&") if pair}
            for name in names:
                param_counter[name] += 1
                if name in FACET_PARAMS:
                    facet_pages += 1
                    if len(param_samples.get(name, [])) < 5:
                        param_samples.setdefault(name, []).append(url)
                if name in ("lang", "locale", "language", "hl"):
                    lang_param_pages += 1
        path = parsed.path
        if any(c.isupper() for c in path):
            uppercase_paths += 1
        if "_" in path:
            underscore_paths += 1
        if path != "/":
            slug = [s for s in path.split("/") if s][-1] or ""
            if len(slug) > MAX_SLUG_LENGTH:
                long_slugs += 1
            if path.endswith("/"):
                slash_pages += 1
            else:
                no_slash_pages += 1

    total = max(len(pages), 1)
    both_slash = slash_pages > 0 and no_slash_pages > 0
    top_params = param_counter.most_common(10)

    subscores = {
        "parameter_control": 40 if param_pages == 0 else 20 if facet_pages == 0 else 0,
        "readable_paths": 20 if not uppercase_paths and not underscore_paths else 0,
        "slug_length": 20 if long_slugs == 0 else 0,
        "slash_consistency": 20 if not both_slash else 0,
    }
    score = sum(subscores.values())

    checks = [
        {
            "passed": param_pages == 0,
            "label": "No parameterized URLs crawled",
            "detail": f"{param_pages} of {len(pages)} page(s) carry query parameters."
                      if param_pages else "Every crawled URL is clean (no query strings).",
        },
        {
            "passed": facet_pages == 0,
            "label": "No faceted / pagination parameters",
            "detail": f"{facet_pages} page(s) use faceted or pagination parameters "
                      f"(top: {', '.join(n for n, _ in top_params if n in FACET_PARAMS) or 'none'}).",
        },
        {
            "passed": not uppercase_paths and not underscore_paths,
            "label": "Readable lowercase hyphenated paths",
            "detail": f"{uppercase_paths} page(s) with uppercase letters, {underscore_paths} with underscores.",
        },
        {
            "passed": long_slugs == 0,
            "label": "Concise URL slugs",
            "detail": f"{long_slugs} slug(s) exceed {MAX_SLUG_LENGTH} characters.",
        },
        {
            "passed": not both_slash,
            "label": "Trailing-slash consistency",
            "detail": f"{slash_pages} page(s) end with '/' vs {no_slash_pages} without — pick one format."
                      if both_slash else "Trailing slashes are consistent.",
        },
        {
            "passed": lang_param_pages == 0,
            "label": "No locale parameters in URLs",
            "detail": f"{lang_param_pages} page(s) use ?lang= style parameters — "
                      "Google recommends locale subdirectories instead."
                      if lang_param_pages else "No ?lang= style parameters found.",
        },
    ]

    summary = {
        "job_id": job_id,
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "pages_total": len(pages),
        "param_pages": param_pages,
        "facet_pages": facet_pages,
        "top_params": dict(top_params),
        "uppercase_paths": uppercase_paths,
        "underscore_paths": underscore_paths,
        "long_slugs": long_slugs,
        "slash_pages": slash_pages,
        "no_slash_pages": no_slash_pages,
        "lang_param_pages": lang_param_pages,
        "param_samples": param_samples,
        "generated_at": datetime.utcnow(),
    }
    await db.url_hygiene_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("URL hygiene job=%s score=%s params=%s/%s", job_id, score, param_pages, len(pages))
    return summary
