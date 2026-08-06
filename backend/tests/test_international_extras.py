"""Tests for the international-SEO / URL-hygiene / indexation / image-optimization
extras round: hreflang helpers + full audit (self-ref, x-default, valid codes,
reciprocity), sitemap alternate capture, URL parameter/slug heuristics, indexation
SERP degradation, image-format/lazy/dimension heuristics, and chat guidance wiring."""

import pytest

from backend.services.international_seo import (
    _locale_of_path,
    _page_hreflang,
    check_international_seo,
    is_valid_hreflang_code,
)
from backend.services import indexation as idx_mod, image_optimization as img_mod, url_hygiene as uh_mod, international_seo
from backend.services.sitemap import _fetch_sitemap_entries
from backend.services.service_errors import ServiceError
from backend.services import chat_service


class FakeCollection:
    def __init__(self, store):
        self._store = store

    def find(self, q, projection=None):
        return self

    async def to_list(self, length=None):
        items = list(self._store.values())
        return [dict(x) for x in items][:length] if length is not None else [dict(x) for x in items]

    async def count_documents(self, q):
        return len(self._store)

    async def find_one(self, q):
        for v in self._store.values():
            if all(v.get(fk) == fv for fk, fv in q.items()):
                return dict(v)
        return None

    async def update_one(self, q, update, upsert=False):
        key = next(iter(q.values()))
        self._store[key] = {**(self._store.get(key) or {}), **update.get("$set", {})}


class FakeDb:
    def __init__(self):
        self._stores = {
            "pages": {},
            "sitemap_audits": {},
            "hreflang_audits": {},
            "url_hygiene_audits": {},
            "indexation_audits": {},
            "image_optimization_audits": {},
        }

    def __getattr__(self, name):
        if name in self._stores:
            return FakeCollection(self._stores[name])
        raise AttributeError(name)


def _page(url, html):
    return {"job_id": "j1", "url": url, "html": html}


class TestHreflangHelpers:
    def test_valid_codes(self):
        for c in ["en", "x-default", "de-de", "en-gb", "pt-pt", "zh-cn"]:
            assert is_valid_hreflang_code(c)

    def test_invalid_codes(self):
        for c in ["en-uk", "es-419", "pt-braz", "xx", "en-123", "en-XXZZ", "", None]:
            assert not is_valid_hreflang_code(c)

    def test_locale_of_path(self):
        assert _locale_of_path("/en/products") == "en"
        assert _locale_of_path("/de-de/ueber-uns") == "de-de"
        assert _locale_of_path("/products/abc") is None
        assert _locale_of_path("/") is None

    def test_page_hreflang_extracts(self):
        html = (
            '<html lang="en-GB"><head>'
            '<link rel="alternate" hreflang="en-gb" href="https://x.example/en/">'
            '<link rel="alternate" hreflang="de-de" href="https://x.example/de-de/">'
            '<link rel="alternate" hreflang="x-default" href="https://x.example/">'
            '<link rel="canonical" href="https://x.example/en/">'
            "</head></html>"
        )
        alts, html_lang, content_lang, canonical = _page_hreflang(html)
        assert alts == {"en-gb": "https://x.example/en/", "de-de": "https://x.example/de-de/", "x-default": "https://x.example/"}
        assert html_lang == "en-gb"
        assert canonical == "https://x.example/en/"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_sitemap_captures_xhtml_alternates(self, monkeypatch):
        xml = (
            '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
            '<url><loc>https://x.example/en/</loc>'
            '<xhtml:link rel="alternate" hreflang="en-GB" href="https://x.example/en/"/>'
            '<xhtml:link rel="alternate" hreflang="de-DE" href="https://x.example/de-de/"/></url>'
            "</urlset>"
        )
        entries = await _fetch_sitemap_entries(xml)
        assert entries[0]["alternates"] == {
            "en-gb": "https://x.example/en/",
            "de-de": "https://x.example/de-de/",
        }


class TestInternationalSeoAudit:
    @pytest.mark.asyncio
    async def test_monolingual_not_applicable(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(international_seo, "get_db", lambda: db)
        db._stores["pages"] = {u: _page(u, "<html><body>hi</body></html>") for u in
                                ["https://x.example/", "https://x.example/about"]}
        summary = await check_international_seo("j1", "https://x.example")
        assert summary["applicable"] is False
        assert summary["score"] is None
        assert summary["checks"][0]["passed"] is True

    @pytest.mark.asyncio
    async def test_multilingual_flags_issues(self, monkeypatch):
        en = (
            '<html><head>'
            '<link rel="alternate" hreflang="en" href="https://x.example/en/">'
            '<link rel="alternate" hreflang="fr" href="https://x.example/fr/">'
            "</head></html>"
        )
        fr = (
            '<html><head>'
            '<link rel="alternate" hreflang="fr" href="https://x.example/fr/">'
            '<link rel="alternate" hreflang="en" href="https://x.example/en/">'
            "</head></html>"
        )
        db = FakeDb()
        monkeypatch.setattr(international_seo, "get_db", lambda: db)
        db._stores["pages"] = {
            "https://x.example/en/": _page("https://x.example/en/", en),
            "https://x.example/fr/": _page("https://x.example/fr/", fr),
        }
        summary = await check_international_seo("j1", "https://x.example")
        assert summary["applicable"] is True
        assert summary["multilingual"] is True
        assert summary["missing_self_ref"] == 0
        assert summary["one_way_pairs_count"] == 0
        assert summary["invalid_codes"] == 0
        assert summary["score"] == 85  # self-ref, codes, reciprocity, locale URLs ok; x-default missing

    @pytest.mark.asyncio
    async def test_missing_self_ref_and_one_way(self, monkeypatch):
        en = (
            '<html><head>'
            '<link rel="alternate" hreflang="en" href="https://x.example/en/">'
            '<link rel="alternate" hreflang="fr" href="https://x.example/fr/">'
            "</head></html>"
        )
        fr = (
            '<html><head>'
            '<link rel="alternate" hreflang="fr" href="https://x.example/fr/">'
            '<link rel="alternate" hreflang="en-uk" href="https://x.example/en-uk/">'
            "</head></html>"
        )
        db = FakeDb()
        monkeypatch.setattr(international_seo, "get_db", lambda: db)
        db._stores["pages"] = {
            "https://x.example/en/": _page("https://x.example/en/", en),
            "https://x.example/fr/": _page("https://x.example/fr/", fr),
        }
        summary = await check_international_seo("j1", "https://x.example")
        assert summary["invalid_codes"] >= 1
        assert summary["one_way_pairs_count"] >= 1

    @pytest.mark.asyncio
    async def test_sitemap_fail_check_when_no_alternates(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(international_seo, "get_db", lambda: db)
        db._stores["pages"] = {
            "https://x.example/en/": _page("https://x.example/en/", ""),
            "https://x.example/fr/": _page("https://x.example/fr/", ""),
        }
        db._stores["sitemap_audits"] = {"j1": {"job_id": "j1", "sitemap_alt_entries": 0,
                                               "sitemap_alt_codes": [], "sitemap_missing_self_ref": 0,
                                               "sitemap_invalid_alt_codes": 0}}
        summary = await check_international_seo("j1", "https://x.example")
        assert summary["applicable"] is True
        assert summary["pages_with_hreflang"] == 0
        assert any(c["label"].startswith("hreflang tags present") and not c["passed"] for c in summary["checks"])


class TestUrlHygiene:
    @pytest.mark.asyncio
    async def test_counts_and_subscore(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(uh_mod, "get_db", lambda: db)
        db._stores["pages"] = {
            "https://x.example/products?&color=red": _page("https://x.example/products?color=red", ""),
            "https://x.example/products?sort=price&page=2": _page("https://x.example/products?sort=price&page=2", ""),
            "https://x.example/MyPAGE/": _page("https://x.example/MyPAGE/", ""),
            "https://x.example/plain/page/": _page("https://x.example/plain/page/", ""),
        }
        summary = await uh_mod.audit_url_hygiene("j1")
        assert summary["param_pages"] >= 2
        assert summary["facet_pages"] >= 1
        assert summary["uppercase_paths"] == 1
        assert "color" in summary["top_params"]
        assert summary["lang_param_pages"] == 0
        assert summary["score"] < 100

    @pytest.mark.asyncio
    async def test_clean_urls_full_score(self, monkeypatch):
        db = FakeDb()
        monkeypatch.setattr(uh_mod, "get_db", lambda: db)
        db._stores["pages"] = {
            "https://x.example/": _page("https://x.example/", ""),
            "https://x.example/products/abc/": _page("https://x.example/products/abc/", ""),
        }
        summary = await uh_mod.audit_url_hygiene("j1")
        assert summary["score"] == 100
        assert all(c["passed"] for c in summary["checks"])


class TestImageOptimization:
    @pytest.mark.asyncio
    async def test_modern_lazy_dims(self, monkeypatch):
        html = (
            "<img src='/img.webp' width='800' height='600' loading='lazy'>"
            "<picture><source type='image/webp' srcset='/a.webp'><source type='image/avif' srcset='/a.avif'>"
            "<img src='/a.jpg'></picture>"
            "<img src='/b.png' loading='lazy'>"
        )
        db = FakeDb()
        monkeypatch.setattr(img_mod, "get_db", lambda: db)
        db._stores["pages"] = {"https://x.example/": _page("https://x.example/", html)}
        summary = await img_mod.audit_image_optimization("j1")
        assert summary["total_images"] == 3
        assert summary["modern_images"] == 2  # webp src + picture source
        assert summary["lazy_images"] == 2
        assert summary["missing_dimensions"] == 2

    @pytest.mark.asyncio
    async def test_scores_formats(self, monkeypatch):
        html = "<img src='/a.png'>"
        db = FakeDb()
        monkeypatch.setattr(img_mod, "get_db", lambda: db)
        db._stores["pages"] = {"https://x.example/": _page("https://x.example/", html)}
        summary = await img_mod.audit_image_optimization("j1")
        assert summary["subscores"]["modern_formats"] == 15
        assert summary["score"] < 100


class TestIndexation:
    @pytest.mark.asyncio
    async def test_unmeasured_on_service_error(self, monkeypatch):
        async def _boom(keyword):
            raise ServiceError("serp", "no serp key", hint="no key configured")

        monkeypatch.setattr("backend.services.indexation.search_keyword", _boom)
        db = FakeDb()
        monkeypatch.setattr(idx_mod, "get_db", lambda: db)
        db._stores["pages"] = {"a": _page("https://x.example/", "")}
        summary = await idx_mod.check_indexation("j1", "https://x.example")
        assert summary["status"] == "unmeasured"
        assert "not run" in summary["message"]
        assert db._stores["indexation_audits"]["j1"]["status"] == "unmeasured"

    @pytest.mark.asyncio
    async def test_measured(self, monkeypatch):
        async def _ok(keyword):
            return {
                "total_results": 940,
                "organic_count": 12,
                "top_results": [
                    {"url": "https://x.example/", "title": "Home"},
                    {"url": "https://other.example/", "title": "Elsewhere"},
                ],
            }

        monkeypatch.setattr("backend.services.indexation.search_keyword", _ok)
        db = FakeDb()
        monkeypatch.setattr(idx_mod, "get_db", lambda: db)
        db._stores["pages"] = {"a": _page("https://x.example/", "")}
        summary = await idx_mod.check_indexation("j1", "https://x.example")
        assert summary["status"] == "measured"
        assert summary["indexed_estimate"] == 940
        assert all("x.example" in t.get("url") for t in summary["top_indexed_pages"])


class TestChatGuidance:
    def test_guidance_constant_present(self):
        assert "hreflang" in chat_service.SEO_AUDIT_GUIDANCE
        assert "x-default" in chat_service.SEO_AUDIT_GUIDANCE

    def test_system_prompt_includes_guidance(self):
        assert "SEO audit guidance" in chat_service.SYSTEM_PROMPT

    def test_general_prompt_includes_guidance(self):
        assert "SEO audit guidance" in chat_service.GENERAL_SYSTEM_PROMPT

    def test_full_site_prompt_covers_new_sections(self):
        assert "hreflang/international" in chat_service.FULL_SITE_PROMPT
        assert "image optimization" in chat_service.FULL_SITE_PROMPT

    def test_issue_key_mapping(self):
        from backend.services.exec_summary import issue_key_from_message
        assert issue_key_from_message("hreflang errors found") == "hreflang_errors"
        assert issue_key_from_message("faceted URL parameters") == "url_param_issues"
        assert issue_key_from_message("image optimization weak") == "image_optimization"