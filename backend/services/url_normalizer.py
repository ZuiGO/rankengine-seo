"""Central URL normalization for all sub-modules.

Canonicalizes a crawled target so the crawler, link checker, performance
audit and duplicate-content checks all agree on what counts as "one page".
"""
from urllib.parse import urlparse, urlunparse

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "ref_url", "fbclid", "gclid", "gclsrc", "dclid",
    "igshid", "mc_cid", "mc_eid", "msclkid", "wbraid",
}

DEFAULT_PORTS = {"http": "80", "https": "443"}


def normalize_url(url: str, strip_tracking: bool = True) -> str:
    """Return a canonical form of a URL, or "" for unusable input.

    Keeps the path (and meaningful query params) but:
      - lowercases scheme + host,
      - drops default ports,
      - strips tracking parameters,
      - canonicalizes trailing slashes (non-root),
      - collapses duplicate slashes in the path.
    """
    if not url or not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlparse(raw)
    except ValueError:
        return ""
    scheme = parts.scheme.lower()
    host = parts.netloc.lower()
    if not scheme or not host:
        return ""

    if ":" in host and host.count(":") == 1:
        h, port = host.rsplit(":", 1)
        if port in DEFAULT_PORTS.get(scheme, ""):
            host = h
    host = host.rstrip(".")

    path = parts.path
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"
    path = _collapse_slashes(path)

    query = ""
    if strip_tracking and parts.query:
        kept = [pair for pair in parts.query.split("&") if pair and pair.split("=", 1)[0].lower() not in TRACKING_PARAMS]
        query = "&".join(kept)
    elif parts.query:
        query = parts.query

    return urlunparse((scheme, host, path, parts.params, query, ""))


def _collapse_slashes(path: str) -> str:
    segs = [s for s in path.split("/") if s]
    joined = "/".join(segs)
    return "/" + joined if joined else "/"


def same_url(a: str, b: str) -> bool:
    return normalize_url(a) == normalize_url(b)