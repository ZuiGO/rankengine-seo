"""Tests for Phase 6: URL normalization + fact-anchored suggestions + keyword extraction."""

from backend.services.url_normalizer import normalize_url, same_url
from backend.services.seo_analyzer import (
    run_item_checks,
    run_extraction_checks,
    run_page_checks,
    _weighted_impact,
)
from backend.services.keyword_extractor import extract_keywords_from_docs, tokenize


class TestUrlNormalizer:
    def test_canonical_trailing_slash(self):
        assert normalize_url("https://Example.com/about/") == "https://example.com/about"

    def test_default_port_stripped(self):
        assert normalize_url("http://example.com:80/About") == "http://example.com/About"
        assert normalize_url("https://example.com:443/x") == "https://example.com/x"

    def test_tracking_params_stripped_others_kept(self):
        assert normalize_url("https://example.com/page?utm_source=g&id=5") == "https://example.com/page?id=5"

    def test_duplicate_slashes_collapsed(self):
        assert normalize_url("https://example.com//a//b/") == "https://example.com/a/b"

    def test_root_url(self):
        assert normalize_url("https://example.com") == "https://example.com/"

    def test_empty_and_schemaless(self):
        assert normalize_url("") == ""
        assert normalize_url("example.com/x") == "https://example.com/x"

    def test_same_url(self):
        assert same_url("https://x.com/a/", "https://x.com/a")
        assert not same_url("https://x.com/a", "https://x.com/b")


class TestItemChecks:
    def test_image_with_alt_no_issues(self):
        checks = run_item_checks({
            "content_type": "image",
            "alt": "Blue widget on a desk",
            "source_url": "https://x.com/img/photo.jpg",
            "file_size": 50000,
        })
        assert checks == []

    def test_image_missing_alt(self):
        checks = run_item_checks({"content_type": "image", "alt": "", "source_url": "https://x.com/i.jpg"})
        keys = [c["issue_key"] for c in checks]
        assert "image_alt_missing" in keys
        assert all(c["confidence"] == 1.0 for c in checks)

    def test_image_generic_alt(self):
        checks = run_item_checks({"content_type": "image", "alt": "pic", "source_url": "https://x.com/i.jpg"})
        assert any(c["issue_key"] == "image_alt_generic" for c in checks)

    def test_image_alt_is_filename(self):
        checks = run_item_checks({"content_type": "image", "alt": "photo.jpg", "source_url": "https://x.com/photo.jpg"})
        assert any(c["issue_key"] == "image_alt_is_filename" for c in checks)

    def test_image_oversized(self):
        checks = run_item_checks({
            "content_type": "image",
            "alt": "fine description",
            "source_url": "https://x.com/i.jpg",
            "file_size": 500_000,
        })
        assert any(c["issue_key"] == "image_oversized" for c in checks)

    def test_video_self_hosted(self):
        checks = run_item_checks({
            "content_type": "video",
            "source_url": "https://x.com/videos/tour.mp4",
            "page_url": "https://x.com/tour",
        })
        assert any(c["issue_key"] == "video_self_hosted" for c in checks)
        assert run_item_checks({
            "content_type": "video",
            "source_url": "https://youtube.com/watch?v=1",
            "page_url": "https://x.com/tour",
        }) == []

    def test_doc_oversized(self):
        checks = run_item_checks({
            "content_type": "pdf",
            "source_url": "https://x.com/big.pdf",
            "file_size": 20_000_000,
        })
        assert any(c["issue_key"] == "document_oversized" for c in checks)


class TestExtractionChecks:
    def test_pdf_no_text_layer(self):
        checks = run_extraction_checks({"content_type": "pdf", "word_count": 0})
        assert any(c["issue_key"] == "pdf_no_text_layer" for c in checks)

    def test_pdf_with_text_ok(self):
        assert run_extraction_checks({"content_type": "pdf", "word_count": 1200}) == []

    def test_doc_extraction_failed(self):
        checks = run_extraction_checks({"content_type": "xlsx", "error": "corrupt file"})
        assert any(c["issue_key"] == "document_extraction_failed" for c in checks)


class TestPageChecks:
    def _page(self, **kw):
        base = {
            "url": "https://x.com/p",
            "word_count": 500,
            "meta_description": "A sufficiently long meta description for the page.",
            "h1_count": 1,
            "is_indexable": True,
            "image_count": 0,
            "images_missing_alt": 0,
        }
        base.update(kw)
        return base

    def test_clean_page_no_issues(self):
        assert run_page_checks(self._page()) == []

    def test_thin_content(self):
        checks = run_page_checks(self._page(word_count=120))
        assert any(c["issue_key"] == "thin_content" for c in checks)

    def test_thin_noindex_not_flagged(self):
        checks = run_page_checks(self._page(word_count=80, is_indexable=False))
        assert not any(c["issue_key"] == "thin_content" for c in checks)
        assert any(c["issue_key"] == "noindex_page" for c in checks)

    def test_meta_missing_and_short(self):
        assert any(c["issue_key"] == "meta_description_missing" for c in run_page_checks(self._page(meta_description="")))
        assert any(c["issue_key"] == "meta_description_short" for c in run_page_checks(self._page(meta_description="tiny")))

    def test_meta_duplicate(self):
        ctx = {"meta_counts": {"shared meta": 3}}
        checks = run_page_checks(self._page(meta_description="shared meta"), ctx)
        assert any(c["issue_key"] == "meta_description_duplicate" for c in checks)

    def test_h1_missing_and_multiple(self):
        assert any(c["issue_key"] == "h1_missing" for c in run_page_checks(self._page(h1_count=0)))
        assert any(c["issue_key"] == "h1_multiple" for c in run_page_checks(self._page(h1_count=3)))

    def test_images_missing_alt_ratio(self):
        checks = run_page_checks(self._page(image_count=10, images_missing_alt=6))
        assert any(c["issue_key"] == "page_images_missing_alt" for c in checks)
        assert run_page_checks(self._page(image_count=10, images_missing_alt=2)) == []


class TestWeightedImpact:
    def test_no_learning_neutral(self):
        assert _weighted_impact("medium", None) == ("medium", False)
        assert _weighted_impact("medium", {"n": 3, "rate": 1.0}) == ("medium", False)

    def test_promote_on_high_approval(self):
        assert _weighted_impact("low", {"n": 8, "rate": 0.85}) == ("medium", False)
        assert _weighted_impact("medium", {"n": 8, "rate": 0.85}) == ("high", False)

    def test_demote_on_low_approval(self):
        impact, demoted = _weighted_impact("high", {"n": 8, "rate": 0.1})
        assert impact == "high" and demoted is True


class TestKeywordExtractor:
    def test_tokenize_stopwords(self):
        toks = tokenize("The quick brown fox jumps over the lazy dog page html")
        assert "quick" in toks and "the" not in toks and "page" not in toks

    def test_common_terms_ranked(self):
        docs = [
            "organic coffee beans roasted in colombia coffee",
            "coffee beans wholesale colombia organic coffee",
            "colombia coffee beans price per kilo coffee",
        ]
        keywords = extract_keywords_from_docs(docs, top_k=5)
        assert "coffee" in keywords
        assert "colombia" in keywords
        assert "beans" in keywords

    def test_singletons_excluded(self):
        docs = ["coffee beans", "tea leaves", "juice bottles"]
        keywords = extract_keywords_from_docs(docs, top_k=10)
        assert "coffee" not in keywords

    def test_empty_corpus(self):
        assert extract_keywords_from_docs([], 5) == []
