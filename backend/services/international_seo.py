"""International-SEO / hreflang audit (offline, crawl-derived).

Follows the seo-audit skill's i18n checklist (MIT-licensed reference): hreflang
self-references, reciprocal pairs, valid language codes, x-default, canonical
alignment, locale-in-URL structure, and sitemap <xhtml:link> alternates. Every
finding is measured from crawled HTML + the sitemap audit — nothing is assumed.
"""

import re
from datetime import datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from backend.db.mongo import get_db
from backend.logging_setup import get_logger
from backend.services.url_normalizer import normalize_url

logger = get_logger("international_seo")

LANG_CODES = {
    "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
    "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs", "ca", "ce",
    "ch", "co", "cr", "cs", "cu", "cv", "cy", "da", "de", "dv", "dz", "ee",
    "el", "en", "eo", "es", "et", "eu", "fa", "ff", "fi", "fj", "fo", "fr",
    "fy", "ga", "gd", "gl", "gn", "gu", "gv", "ha", "he", "hi", "ho", "hr",
    "ht", "hu", "hy", "hz", "ia", "id", "ie", "ig", "ii", "ik", "io", "is",
    "it", "iu", "ja", "jv", "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn",
    "ko", "kr", "ks", "ku", "kv", "kw", "ky", "la", "lb", "lg", "li", "ln",
    "lo", "lt", "lu", "lv", "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms",
    "mt", "my", "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv",
    "ny", "oc", "oj", "om", "or", "os", "pa", "pi", "pl", "ps", "pt", "qu",
    "rm", "rn", "ro", "ru", "rw", "sa", "sc", "sd", "se", "sg", "si", "sk",
    "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw", "ta",
    "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw",
    "ty", "ug", "uk", "ur", "uz", "ve", "vi", "vo", "wa", "wo", "xh", "yi",
    "yo", "za", "zh", "zu",
}

REGIONS = {
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT",
    "AU", "AW", "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI",
    "BJ", "BL", "BM", "BN", "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY",
    "BZ", "CA", "CC", "CD", "CF", "CG", "CH", "CI", "CK", "CL", "CM", "CN",
    "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ", "DE", "DJ", "DK", "DM",
    "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI", "FJ", "FK",
    "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM",
    "HN", "HR", "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR",
    "IS", "IT", "JE", "JM", "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN",
    "KP", "KR", "KW", "KY", "KZ", "LA", "LB", "LC", "LI", "LK", "LR", "LS",
    "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME", "MF", "MG", "MH", "MK",
    "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU", "MV", "MW",
    "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM",
    "PN", "PR", "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW",
    "SA", "SB", "SC", "SD", "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM",
    "SN", "SO", "SR", "SS", "ST", "SV", "SX", "SY", "SZ", "TC", "TD", "TF",
    "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO", "TR", "TT", "TV", "TW",
    "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE", "VG", "VI",
    "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
}

KNOWN_BAD_CODES = {"en-uk", "es-419", "pt-braz"}

LOCALE_PARAM_NAMES = {"lang", "locale", "language", "hl"}


def is_valid_hreflang_code(code: str) -> bool:
    """True for x-default or valid `language[-region]` codes (ISO 639-1 + ISO 3166-1)."""
    if not code:
        return False
    c = code.strip().lower()
    if c == "x-default":
        return True
    if c in KNOWN_BAD_CODES:
        return False
    parts = c.split("-")
    if len(parts) == 1:
        return parts[0] in LANG_CODES
    if len(parts) == 2:
        return parts[0] in LANG_CODES and parts[1].upper() in REGIONS
    return False


def _locale_of_path(path: str) -> str | None:
    """Return the locale token of a /xx/ or /xx-YY/ first path segment, if any."""
    segs = [s for s in path.split("/") if s]
    if not segs:
        return None
    seg = segs[0].lower()
    if seg in LANG_CODES or (seg.split("-")[0] in LANG_CODES and seg.split("-")[1].upper() in REGIONS):
        return seg
    return None


def _page_hreflang(html: str) -> tuple[dict[str, str], str | None, str | None, str | None]:
    """Return (alternates {code: href}, html_lang, content_lang, canonical)."""
    if not html:
        return {}, None, None, None
    soup = BeautifulSoup(html, "lxml")
    alternates: dict[str, str] = {}
    for link in soup.find_all("link", rel="alternate"):
        code = (link.get("hreflang") or "").strip().lower()
        href = (link.get("href") or "").strip()
        if code and href:
            alternates[code] = href
    html_lang = None
    if soup.html and soup.html.get("lang"):
        html_lang = soup.html["lang"].strip().lower()
    content_lang = None
    meta = soup.find("meta", attrs={"http-equiv": "content-language"})
    if meta and meta.get("content"):
        content_lang = meta["content"].strip().lower()
    canonical = None
    for link in soup.find_all("link", rel="canonical"):
        canonical = (link.get("href") or "").strip()
        if canonical:
            break
    return alternates, html_lang, content_lang, canonical


async def check_international_seo(job_id: str, target_url: str) -> dict:
    db = get_db()
    pages = await db.pages.find({"job_id": job_id}, {"html": 1, "url": 1}).to_list(length=None)

    page_data = {}
    for p in pages:
        url = p.get("url") or ""
        html = p.get("html") or ""
        alts, html_lang, content_lang, canonical = _page_hreflang(html)
        page_data[url] = {
            "alternates": alts,
            "html_lang": html_lang,
            "content_lang": content_lang,
            "canonical": canonical,
        }

    pages_with_hreflang = sum(1 for d in page_data.values() if d["alternates"])
    locales: set[str] = set()
    for d in page_data.values():
        for code in d["alternates"]:
            if code != "x-default":
                locales.add(code)
    for url in page_data:
        loc = _locale_of_path(urlparse(url).path)
        if loc:
            locales.add(loc)
        for pname in LOCALE_PARAM_NAMES:
            if pname + "=" in (urlparse(url).query or ""):
                locales.add(pname)

    multilingual = len(locales) >= 2
    applicable = multilingual or pages_with_hreflang > 0

    missing_self_ref = 0
    missing_xdefault = 0
    invalid_codes = 0
    one_way_pairs = []
    canonical_conflicts = []
    locale_hidden = []
    lang_param_pages = 0
    html_lang_missing = 0
    self_ref_pages = 0

    norm_by_url = {normalize_url(u): u for u in page_data if normalize_url(u)}
    for url, d in page_data.items():
        alts = d["alternates"]
        if not alts:
            continue
        norm = normalize_url(url)
        targets = {normalize_url(h) for h in alts.values() if normalize_url(h)}
        if norm in targets:
            self_ref_pages += 1
        else:
            missing_self_ref += 1
        if "x-default" not in alts:
            missing_xdefault += 1
        for code in alts:
            if not is_valid_hreflang_code(code):
                invalid_codes += 1
        if not d["html_lang"] and not d["content_lang"]:
            html_lang_missing += 1
        if d["canonical"]:
            cnorm = normalize_url(d["canonical"])
            if cnorm and targets and cnorm not in targets:
                canonical_conflicts.append(url)
        for code, href in alts.items():
            if code == "x-default":
                continue
            tnorm = normalize_url(href)
            back = norm_by_url.get(tnorm)
            if back is None:
                continue
            back_alts = page_data[back]["alternates"]
            if not back_alts or norm not in {normalize_url(h) for h in back_alts.values()}:
                one_way_pairs.append(f"{code}: {url} -> {back}")
        if multilingual:
            path = urlparse(url).path
            query = urlparse(url).query or ""
            has_locale = _locale_of_path(path) is not None or any(
                pn + "=" in query for pn in LOCALE_PARAM_NAMES
            )
            if not has_locale and len(locales) >= 2:
                locale_hidden.append(url)
        if any(pn + "=" in (urlparse(url).query or "") for pn in LOCALE_PARAM_NAMES):
            lang_param_pages += 1

    sitemap_doc = await db.sitemap_audits.find_one({"job_id": job_id})
    sitemap_stats = {
        "entries_with_alternates": (sitemap_doc or {}).get("sitemap_alt_entries", 0),
        "alt_codes": (sitemap_doc or {}).get("sitemap_alt_codes", []),
        "missing_self_ref": (sitemap_doc or {}).get("sitemap_missing_self_ref", 0),
        "invalid_alt_codes": (sitemap_doc or {}).get("sitemap_invalid_alt_codes", 0),
    }

    total_hreflang = max(pages_with_hreflang, 1)
    subscores = {
        "self_reference": 30 if missing_self_ref == 0 else 0,
        "x_default": 15 if missing_xdefault == 0 else 0,
        "valid_codes": 15 if invalid_codes == 0 else 0,
        "reciprocal": 25 if not one_way_pairs else 0,
        "locale_urls": 15 if (not locale_hidden and lang_param_pages == 0) else 0,
    }
    score = sum(subscores.values()) if applicable else None

    checks = []
    if not applicable:
        checks.append({
            "passed": True,
            "label": "Site appears monolingual",
            "detail": "No hreflang tags and no multi-locale URL structure detected — international-SEO checks do not apply.",
        })
    else:
        if pages_with_hreflang == 0:
            checks.append({
                "passed": False,
                "label": "hreflang tags present on localized pages",
                "detail": f"Detected {len(locales)} locale(s) but no page declares <link rel='alternate' hreflang>. "
                          "Without hreflang, Google may index the wrong locale variant.",
            })
        checks.append({
            "passed": missing_self_ref == 0,
            "label": "Every hreflang page includes itself (self-referencing)",
            "detail": f"{missing_self_ref} of {pages_with_hreflang} hreflang page(s) lack their own URL in the alternate set.",
        })
        checks.append({
            "passed": missing_xdefault == 0,
            "label": "x-default fallback declared",
            "detail": f"{missing_xdefault} page(s) with hreflang miss the x-default variant.",
        })
        checks.append({
            "passed": invalid_codes == 0,
            "label": "Valid language-region codes",
            "detail": f"{invalid_codes} invalid hreflang code(s) (e.g. en-UK should be en-GB).",
        })
        checks.append({
            "passed": not one_way_pairs,
            "label": "Reciprocal hreflang pairs",
            "detail": f"{len(one_way_pairs)} one-directional pair(s) — Google ignores non-reciprocal annotations."
                      if one_way_pairs else "All in-site alternate targets link back.",
        })
        checks.append({
            "passed": not canonical_conflicts,
            "label": "Canonical URL belongs to the hreflang set",
            "detail": f"{len(canonical_conflicts)} page(s) canonical to a URL outside their alternate set — "
                      "the canonical overrides hreflang."
                      if canonical_conflicts else "Canonical and hreflang clusters align.",
        })
        checks.append({
            "passed": not locale_hidden and lang_param_pages == 0,
            "label": "Locale visible in the URL",
            "detail": (f"{len(locale_hidden)} page(s) have no locale prefix (use /en/, /de/ subdirectories)."
                       if locale_hidden else "")
                      + (f" {lang_param_pages} page(s) use ?lang= URL parameters (not recommended)."
                         if lang_param_pages else ""),
        })
        if sitemap_stats["entries_with_alternates"]:
            checks.append({
                "passed": sitemap_stats["missing_self_ref"] == 0 and sitemap_stats["invalid_alt_codes"] == 0,
                "label": "Sitemap <xhtml:link> alternates are complete",
                "detail": (f"{sitemap_stats['entries_with_alternates']} sitemap URL(s) carry alternates; "
                           f"{sitemap_stats['missing_self_ref']} missing self-reference, "
                           f"{sitemap_stats['invalid_alt_codes']} with invalid codes."),
            })
        else:
            checks.append({
                "passed": pages_with_hreflang == 0,
                "label": "Sitemap carries hreflang alternates",
                "detail": "No <xhtml:link rel='alternate'> entries found in the sitemap."
                          if pages_with_hreflang else "Monolingual site — not required.",
            })

    summary = {
        "job_id": job_id,
        "url": target_url,
        "multilingual": multilingual,
        "applicable": applicable,
        "locales": sorted(locales),
        "score": score,
        "subscores": subscores,
        "checks": checks,
        "pages_with_hreflang": pages_with_hreflang,
        "pages_total": len(page_data),
        "missing_self_ref": missing_self_ref,
        "missing_xdefault": missing_xdefault,
        "invalid_codes": invalid_codes,
        "one_way_pairs_count": len(one_way_pairs),
        "canonical_conflicts_count": len(canonical_conflicts),
        "locale_hidden_count": len(locale_hidden),
        "lang_param_pages": lang_param_pages,
        "html_lang_missing": html_lang_missing,
        "sitemap": sitemap_stats,
        "samples": {
            "one_way_pairs": one_way_pairs[:8],
            "canonical_conflicts": canonical_conflicts[:8],
            "locale_hidden": locale_hidden[:8],
        },
        "generated_at": datetime.utcnow(),
    }
    await db.hreflang_audits.update_one(
        {"job_id": job_id},
        {"$set": summary},
        upsert=True,
    )
    logger.info("International SEO job=%s applicable=%s locales=%s score=%s",
                job_id, applicable, len(locales), score)
    return summary
