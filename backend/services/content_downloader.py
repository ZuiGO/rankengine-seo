import aiofiles
import httpx
import os
from urllib.parse import urlparse

DOWNLOAD_DIR = "./downloads"


async def download_content(source_url: str, job_id: str, page_url: str) -> dict | None:
    parsed = urlparse(source_url)
    ext = os.path.splitext(parsed.path)[1] or ".bin"
    safe_name = parsed.path.replace("/", "_").strip("_")
    if not safe_name:
        safe_name = f"file_{hash(source_url) % 10000}"
    filename = f"{safe_name}{ext}"
    dir_path = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(dir_path, exist_ok=True)
    filepath = os.path.join(dir_path, filename)

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(source_url)
            resp.raise_for_status()
            content = resp.content
            mime = resp.headers.get("content-type", "")

            async with aiofiles.open(filepath, "wb") as f:
                await f.write(content)

            return {
                "file_path": filepath,
                "file_size": len(content),
                "mime_type": mime,
                "filename": filename,
            }
    except Exception:
        return None


async def probe_content(source_url: str, job_id: str, page_url: str) -> dict | None:
    """Metadata-only probe: size + mime via HEAD (GET-stream fallback), no body stored."""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.head(source_url)
            if resp.status_code >= 400:
                resp = await client.get(source_url)
            mime = resp.headers.get("content-type", "")
            size_hdr = resp.headers.get("content-length")
            return {
                "file_path": None,
                "file_size": int(size_hdr) if size_hdr and size_hdr.isdigit() else None,
                "mime_type": mime,
                "filename": None,
            }
    except Exception:
        return None
