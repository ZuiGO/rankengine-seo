"""Extract structured content model from raw HTML for staging pages."""

import re
from typing import Any
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup


def extract_content_model(html: str, base_url: str) -> dict[str, Any]:
    """Parse raw HTML and return a structured content model."""
    soup = BeautifulSoup(html, "lxml")

    model = {
        "title": _extract_title(soup),
        "meta_description": _extract_meta_description(soup),
        "headings": _extract_headings(soup),
        "body_paragraphs": _extract_body_paragraphs(soup),
        "images": _extract_images(soup, base_url),
        "links": _extract_links(soup, base_url),
        "schema_jsonld": _extract_schema_jsonld(soup),
    }

    facts = _derive_facts(model, soup, base_url)
    model["facts"] = facts

    return model


def _extract_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    return title_tag.get_text(strip=True) if title_tag else ""


def _extract_meta_description(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"].strip()
    og_meta = soup.find("meta", attrs={"property": "og:description"})
    if og_meta and og_meta.get("content"):
        return og_meta["content"].strip()
    return ""


def _extract_headings(soup: BeautifulSoup) -> list[dict]:
    headings = []
    for h in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        selector = _build_selector(h)
        headings.append({
            "level": int(h.name[1]),
            "text": h.get_text(strip=True),
            "selector": selector,
        })
    return headings


def _extract_body_paragraphs(soup: BeautifulSoup) -> list[dict]:
    paragraphs = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if not text:
            continue
        selector = _build_selector(p)
        paragraphs.append({
            "text": text,
            "html": str(p),
            "selector": selector,
        })
    for li in soup.find_all("li"):
        text = li.get_text(strip=True)
        if not text:
            continue
        selector = _build_selector(li)
        paragraphs.append({
            "text": text,
            "html": str(li),
            "selector": selector,
        })
    return paragraphs


def _extract_images(soup: BeautifulSoup, base_url: str) -> list[dict]:
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src:
            continue
        src = urljoin(base_url, src)
        selector = _build_selector(img)
        images.append({
            "src": src,
            "alt": img.get("alt", ""),
            "selector": selector,
        })
    return images


def _extract_links(soup: BeautifulSoup, base_url: str) -> list[dict]:
    links = []
    base_host = urlparse(base_url).netloc
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        selector = _build_selector(a)
        links.append({
            "href": full,
            "text": a.get_text(strip=True),
            "selector": selector,
            "is_internal": parsed.netloc == base_host,
        })
    return links


def _extract_schema_jsonld(soup: BeautifulSoup) -> list[dict]:
    schemas = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or "{}")
            if isinstance(data, list):
                schemas.extend(data)
            else:
                schemas.append(data)
        except Exception:
            continue
    return schemas


def _build_selector(element) -> str:
    """Build a simple CSS selector for an element."""
    parts = []
    el = element
    while el and el.name != "body":
        part = el.name
        if el.get("id"):
            part = f"{part}#{el['id']}"
        elif el.get("class"):
            classes = ".".join(el.get("class", []))
            part = f"{part}.{classes}"
        parts.append(part)
        el = el.parent
    return " > ".join(reversed(parts)) if parts else "body"


def _derive_facts(model: dict, soup: BeautifulSoup, base_url: str) -> dict:
    """Derive boolean/quantitative facts used as evidence for suggestion generation."""
    facts = {
        "title_length": len(model["title"]),
        "has_meta_description": bool(model["meta_description"]),
        "meta_description_length": len(model["meta_description"]),
        "h1_count": sum(1 for h in model["headings"] if h["level"] == 1),
        "h2_count": sum(1 for h in model["headings"] if h["level"] == 2),
        "has_jsonld": len(model["schema_jsonld"]) > 0,
        "images_missing_alt": sum(1 for img in model["images"] if not img["alt"]),
        "body_internal_link_count": sum(1 for l in model["links"] if l["is_internal"]),
        "body_external_link_count": sum(1 for l in model["links"] if not l["is_internal"]),
        "paragraph_count": len(model["body_paragraphs"]),
        "word_count": sum(len(p["text"].split()) for p in model["body_paragraphs"]),
    }
    return facts