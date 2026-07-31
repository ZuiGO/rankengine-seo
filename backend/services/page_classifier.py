import re
from urllib.parse import urlparse


PAGE_TYPES = [
    "home",
    "product",
    "category",
    "blog",
    "content",
    "landing",
    "support",
    "corporate",
    "conversion",
    "other",
]

PAGE_ROLES = {
    "home": "entry",
    "landing": "entry",
    "blog": "entry",
    "category": "browse",
    "content": "browse",
    "product": "action",
    "conversion": "action",
    "support": "action",
    "corporate": "browse",
    "other": "browse",
}

_PATTERN_RULES = [
    (re.compile(r"/(product|products|item|items|dp|gp|detail|sku|stock)(/|$|\?|#)", re.I), "product"),
    (re.compile(r"/page-\d+(\.html?)?($|\?|#)", re.I), "category"),
    (re.compile(r"/page/\d+/?($|\?|#)", re.I), "category"),
    (re.compile(r"/category/[^/?#]*_\d+(/index\.html?)?($|\?|#)", re.I), "category"),
    (re.compile(r"(?:^|/)[^/?#]*_\d+(/index\.html?)?($|\?|#)", re.I), "product"),
    (re.compile(r"/(category|catalogue|catalog|collection|shop|store|browse|search|listing|all)(/|$|\?|#)", re.I), "category"),
    (re.compile(r"/(blog|news|article|articles|post|posts|stories?|journal|insights?|resources)(/|$|\?|#)", re.I), "blog"),
    (re.compile(r"/(docs|documentation|help|support|faq|kb|knowledge-base|tutorials?|manual)(/|$|\?|#)", re.I), "support"),
    (re.compile(r"/(about|about-us|contact|contact-us|team|careers?|privacy|privacy-policy|terms|terms-of-service|legal|press)(/|$|\?|#)", re.I), "corporate"),
    (re.compile(r"/(cart|checkout|account|login|signup|sign-in|register|checkout-single)(/|$|\?|#)", re.I), "conversion"),
    (re.compile(r"/(landing|lp|offer|promo|launch|campaign)(/|$|\?|#)", re.I), "landing"),
    (re.compile(r"/_|/download|/pdf|/files?/|/assets?/", re.I), "content"),
]

_PRODUCT_SIGNALS = [
    re.compile(r"\b(price|add to cart|add to bag|buy now|purchase|out of stock|in stock|sku|shipping)\b", re.I),
]
_CATEGORY_SIGNALS = [
    re.compile(r"\b(filter by|sort by|showing \d+|results? for|items? per page)\b", re.I),
]
_ARTICLE_SIGNALS = [
    re.compile(r"\b(read more|published|by \w+ (author|writer|editor)|comments?\b)", re.I),
]


def classify_page_type(url: str, soup=None, title: str = "", meta_description: str = "") -> str:
    path = urlparse(url).path.strip("/")
    if not path or path.lower() in ("index.html", "index.htm", "index.php", "default.html"):
        return "home"

    for pattern, ptype in _PATTERN_RULES:
        if pattern.search(url):
            return ptype

    text = ""
    if soup is not None:
        text = soup.get_text(separator=" ", strip=True)[:2000].lower()

    title_lower = title.lower()
    meta_lower = meta_description.lower()

    if any(p.search(text) for p in _PRODUCT_SIGNALS):
        return "product"
    if any(p.search(text) for p in _CATEGORY_SIGNALS):
        return "category"
    if any(p.search(text) for p in _ARTICLE_SIGNALS) or "article" in title_lower or "blog" in title_lower:
        return "blog"
    if any(word in title_lower or word in meta_lower for word in
           ["documentation", "support", "help", "faq", "guide", "manual"]):
        return "support"
    if any(word in title_lower or word in meta_lower for word in
           ["about", "contact", "team", "careers", "privacy", "terms"]):
        return "corporate"

    return "other"


def page_role(page_type: str) -> str:
    return PAGE_ROLES.get(page_type, "browse")
