"""Content-level AI-readiness signals: E-E-A-T markers and answer-extractable
formatting, computed from page HTML without external lookups.
"""

import re
from bs4 import BeautifulSoup


def _attr(soup: BeautifulSoup, selector: str, **kw):
    node = soup.select_one(selector)
    if node is None:
        return None
    if kw.get("text"):
        return node.get_text(" ", strip=True)
    return node.attrs.get(kw.get("name", "content"), "") or None


def compute_page_signals(html: str) -> dict:
    soup = BeautifulSoup(html or "", "lxml")

    present = []
    missing = []

    author = _attr(soup, 'meta[name="author"], meta[property="article:author"]')
    if author:
        present.append("author")
    else:
        missing.append("author")

    about_link = soup.find("a", href=re.compile(r"about", re.I))
    contact_link = soup.find("a", href=re.compile(r"contact", re.I))
    if about_link or contact_link:
        present.append("about/contact")
    else:
        missing.append("about/contact page")

    updated = _attr(soup, 'meta[property="article:modified_time"], meta[name="last-modified"]') or ""
    if updated:
        present.append("last-updated")
    else:
        missing.append("last-updated date")

    publisher = _attr(soup, 'meta[property="og:site_name"], meta[name="publisher"]')
    if publisher:
        present.append("publisher")
    else:
        missing.append("publisher/org")

    corporate = soup.find("script", text=re.compile(r"(LocalBusiness|Organization)", re.I))
    if corporate:
        present.append("organization schema")
    else:
        missing.append("organization schema")

    faq = bool(soup.select("details, .faq, [class*='faq']")) or len(_h_faq(soup)) > 0
    lists_count = len(soup.select("ul, ol")) + len(soup.select("table")) + len(soup.select("dl"))
    extractable_format = bool(faq) or lists_count >= 3

    definitions = soup.select("dl")
    definition_lists = len(definitions)
    tables = len(soup.select("table"))
    unordered_lists = len(soup.select("ul"))
    ordered_lists = len(soup.select("ol"))

    return {
        "present": present,
        "missing_signals": missing,
        "extractable_format": extractable_format,
        "faq_sections": int(faq),
        "tables": tables,
        "lists": unordered_lists + ordered_lists,
        "definition_lists": definition_lists,
    }


def _h_faq(soup: BeautifulSoup) -> list:
    headings = []
    for node in soup.find_all(["h2", "h3"]):
        text = node.get_text(" ", strip=True).lower()
        if text.startswith(("faq", "frequently asked", "questions")):
            headings.append(text)
    return headings