import mimetypes
import os
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

CONTENT_PATTERNS = {
    "pdf": (r"\.pdf($|\?|#)", "application/pdf"),
    "video": (r"\.(mp4|webm|avi|mov|mkv|wmv|flv|3gp)($|\?|#)", "video/"),
    "presentation": (r"(slideshare|docs\.google\.com/presentation|speakerdeck)", "text/html"),
    "doc": (r"\.(doc|docx|odt|rtf)($|\?|#)", "application/msword"),
    "xlsx": (r"\.(xls|xlsx|csv|ods)($|\?|#)", "application/vnd.ms-excel"),
    "image": (r"\.(jpg|jpeg|png|gif|webp|svg|avif|bmp|ico)($|\?|#)", "image/"),
    "audio": (r"\.(mp3|wav|ogg|aac|flac|wma|m4a)($|\?|#)", "audio/"),
    "archive": (r"\.(zip|tar|gz|rar|7z)($|\?|#)", "application/zip"),
}

YOUTUBE_DOMAINS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
VIMEO_DOMAINS = {"vimeo.com", "player.vimeo.com"}
GOOGLE_DOCS_DOMAINS = {"docs.google.com", "sheets.google.com", "slides.google.com"}


def classify_url(href: str) -> str | None:
    for ctype, (pattern, _) in CONTENT_PATTERNS.items():
        if re.search(pattern, href, re.IGNORECASE):
            return ctype
    parsed = urlparse(href)
    domain = parsed.netloc.lower()
    if domain in YOUTUBE_DOMAINS:
        return "video_embed"
    if domain in VIMEO_DOMAINS:
        return "video_embed"
    if domain in GOOGLE_DOCS_DOMAINS:
        path = parsed.path.lower()
        if "/document/" in path:
            return "doc"
        if "/spreadsheets/" in path:
            return "xlsx"
        if "/presentation/" in path:
            return "presentation"
    return None


def classify_with_magic(file_path: str) -> str | None:
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    mime_map = {
        "pdf": "pdf",
        "jpg": "image", "jpeg": "image", "png": "image", "gif": "image",
        "webp": "image", "svg": "image", "avif": "image", "bmp": "image", "ico": "image",
        "mp4": "video", "webm": "video", "avi": "video", "mov": "video",
        "mkv": "video", "wmv": "video", "flv": "video",
        "mp3": "audio", "wav": "audio", "ogg": "audio", "aac": "audio", "flac": "audio",
        "doc": "doc", "docx": "doc", "odt": "doc", "rtf": "doc",
        "xls": "xlsx", "xlsx": "xlsx", "csv": "xlsx", "ods": "xlsx",
        "ppt": "presentation", "pptx": "presentation",
        "zip": "archive", "tar": "archive", "gz": "archive", "rar": "archive", "7z": "archive",
    }
    return mime_map.get(ext)


def detect_content_types(page_url: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    seen: set[str] = set()

    joined = lambda url: urljoin(page_url, url.strip()) if url else ""

    def add(ctype: str, source_url: str, **extra) -> None:
        if not source_url or source_url.lower().startswith("data:"):
            return
        if source_url in seen:
            return
        seen.add(source_url)
        items.append({"type": ctype, "source_url": source_url, **extra})

    # Images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        full = joined(src)
        if full:
            add("image", full, alt=img.get("alt", ""), tag="img",
                width=img.get("width"), height=img.get("height"))

    # Picture sources (skip video <source> children — handled below)
    for source in soup.find_all("source"):
        picture = next(
            (a for a in (source.parents if source.parent is not None else iter(()))
             if getattr(a, "name", "") == "picture"),
            None,
        )
        if picture is None:
            continue
        srcset = source.get("srcset", "")
        if srcset:
            first_url = srcset.split(",")[0].strip().split(" ")[0]
            full = joined(first_url)
            if full:
                add("image", full, tag="source", alt="")

    # Links to files / embeds
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        full = joined(href)
        if not full:
            continue
        ctype = classify_url(full)
        if ctype:
            add(ctype, full, text=a.get_text(strip=True), tag="a")

    # YouTube embeds (iframe src)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or ""
        full = joined(src)
        if not full:
            continue
        parsed = urlparse(full)
        domain = parsed.netloc.lower()
        is_embed = any(d in domain for d in (*YOUTUBE_DOMAINS, *VIMEO_DOMAINS))
        add("video_embed" if is_embed else "iframe", full, tag="iframe")

    # Video tags
    for video in soup.find_all("video"):
        src = video.get("src") or ""
        full = joined(src)
        if full:
            add("video", full, tag="video")
        for source in video.find_all("source"):
            s = source.get("src", "")
            full = joined(s)
            if full:
                add("video", full, tag="source")

    # Object / embed tags
    for obj in soup.find_all("object"):
        data = obj.get("data", "")
        full = joined(data)
        if full:
            add("iframe", full, tag="object")

    return items
