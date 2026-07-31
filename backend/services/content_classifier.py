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
        return "video"
    if domain in VIMEO_DOMAINS:
        return "video"
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
    seen = set()

    # Images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        if src and src not in seen:
            seen.add(src)
            items.append({
                "type": "image",
                "source_url": urljoin(page_url, src),
                "alt": img.get("alt", ""),
                "tag": "img",
                "width": img.get("width"),
                "height": img.get("height"),
            })

    # Picture sources
    for source in soup.find_all("source"):
        srcset = source.get("srcset", "")
        if srcset and srcset not in seen:
            first_url = srcset.split(",")[0].strip().split(" ")[0]
            if first_url not in seen:
                seen.add(first_url)
                items.append({
                    "type": "image",
                    "source_url": urljoin(page_url, first_url),
                    "tag": "source",
                    "alt": "",
                })

    # Links to files / embeds
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue
        ctype = classify_url(href)
        if ctype and href not in seen:
            seen.add(href)
            items.append({
                "type": ctype,
                "source_url": urljoin(page_url, href),
                "text": a.get_text(strip=True),
                "tag": "a",
            })

    # YouTube embeds (iframe src)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or ""
        if src and src not in seen:
            seen.add(src)
            full = urljoin(page_url, src)
            parsed = urlparse(full)
            domain = parsed.netloc.lower()
            ctype = "video" if any(d in domain for d in (*YOUTUBE_DOMAINS, *VIMEO_DOMAINS)) else None
            items.append({
                "type": ctype or "iframe",
                "source_url": full,
                "tag": "iframe",
            })

    # Video tags
    for video in soup.find_all("video"):
        src = video.get("src") or ""
        if src and src not in seen:
            seen.add(src)
            items.append({
                "type": "video",
                "source_url": urljoin(page_url, src),
                "tag": "video",
            })
        for source in video.find_all("source"):
            s = source.get("src", "")
            if s and s not in seen:
                seen.add(s)
                items.append({
                    "type": "video",
                    "source_url": urljoin(page_url, s),
                    "tag": "source",
                })

    # Object / embed tags
    for obj in soup.find_all("object"):
        data = obj.get("data", "")
        if data and data not in seen:
            seen.add(data)
            items.append({
                "type": "iframe",
                "source_url": urljoin(page_url, data),
                "tag": "object",
            })

    return items
