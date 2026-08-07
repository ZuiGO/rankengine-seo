"""Exact unique content counts: classifier emits one item per uniquely resolved
URL (no duplicate rows for relative/absolute forms of the same file, no data:
URIs, `<source>` counted only inside <picture>), matching content-items dedup."""

from backend.services.content_classifier import detect_content_types


def _types(items):
    return {(i["type"], i["tag"], i["source_url"]) for i in items}


def test_relative_and_absolute_same_file_dedupe():
    html = (
        "<img src='/logo.png'>"
        "<img src='https://x.example/logo.png'>"
        "<a href='/logo.png'>alt</a>"
    )
    items = detect_content_types("https://x.example/", html)
    by_url = [i for i in items if i["source_url"].endswith("logo.png")]
    assert len(by_url) == 1


def test_data_uri_images_skipped():
    html = "<img src='data:image/svg+xml;base64,PHN2Zz48L3N2Zz4='><img src='/real.png'>"
    items = detect_content_types("https://x.example/", html)
    assert len(items) == 1
    assert items[0]["source_url"] == "https://x.example/real.png"


def test_source_tag_ignored_outside_picture():
    html = (
        "<picture><source srcset='/c.webp'><img src='/c.jpg'></picture>"
        "<video><source src='/clip.mp4'></video>"
        "<source srcset='/stray.webp'>"
    )
    items = detect_content_types("https://x.example/", html)
    image_sources = [i for i in items if i["type"] == "image" and i["tag"] == "source"]
    assert len(image_sources) == 1
    assert image_sources[0]["source_url"] == "https://x.example/c.webp"
    videos = [i for i in items if i["type"] == "video"]
    assert any(i["source_url"] == "https://x.example/clip.mp4" for i in videos)


def test_query_variants_are_distinct_urls():
    html = "<img src='/a.png'><img src='/a.png?v=2'>"
    items = detect_content_types("https://x.example/", html)
    urls = {i["source_url"] for i in items}
    assert urls == {"https://x.example/a.png", "https://x.example/a.png?v=2"}