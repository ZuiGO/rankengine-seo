"""Unit tests for the RankEngine backend (pure logic, no DB/network)."""

import math

import pytest

from backend.services.duplicate_content import canonical_audit
from backend.services.embeddings import VECTOR_DIM, embed_text_hash
from backend.services.geo_alignment import _cosine, _mean_vec, _tokens, _top_keywords
from backend.services.orphan_detection import _norm
from backend.services.site_health import _grade
from backend.services.structured_data import _json_ld_objects, validate_structured_data


class TestHashEmbeddings:
    def test_dimension(self):
        v = embed_text_hash("hello world")
        assert len(v) == VECTOR_DIM

    def test_deterministic(self):
        assert embed_text_hash("seo audit") == embed_text_hash("seo audit")

    def test_normalized(self):
        v = embed_text_hash("rankengine")
        assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6

    def test_similar_vs_dissimilar(self):
        a = embed_text_hash("software development company")
        b = embed_text_hash("software development services")
        c = embed_text_hash("recipe for chocolate cake")
        assert _cosine(a, b) > _cosine(a, c)


class TestGeoAlignment:
    def test_tokens_strip_stopwords(self):
        tokens = _tokens("The company builds secure software for healthcare")
        assert "the" not in tokens
        assert "software" in tokens
        assert "company" not in tokens

    def test_top_keywords_rank_by_frequency(self):
        tokens = ["seo", "seo", "seo", "audit", "audit", "tools"]
        assert _top_keywords(tokens, 3) == ["seo", "audit", "tools"]

    def test_cosine(self):
        assert _cosine([1, 0], [1, 0]) == 1.0
        assert _cosine([1, 0], [0, 1]) == 0.0
        assert _cosine([], [1]) == 0.0

    def test_mean_vec(self):
        assert _mean_vec([[1, 3], [3, 5]]) == [2, 4]
        assert _mean_vec([]) == []


class TestCanonicalAudit:
    def test_missing(self):
        r = canonical_audit("https://x.com/a", "<html><title>t</title></html>")
        assert r["canonical_present"] is False

    def test_self_referencing(self):
        html = '<html><link rel="canonical" href="https://x.com/a"></html>'
        r = canonical_audit("https://x.com/a", html)
        assert r["canonical_self"] is True

    def test_conflicting(self):
        html = '<html><link rel="canonical" href="https://x.com/a"><link rel="canonical" href="https://x.com/b"></html>'
        r = canonical_audit("https://x.com/a", html)
        assert r["canonical_multiple"] is True
        assert r["canonical_conflicting"] is True

    def test_cross_domain(self):
        html = '<html><link rel="canonical" href="https://other.com/page"></html>'
        r = canonical_audit("https://x.com/a", html)
        assert r["canonical_cross_domain"] is True


class TestStructuredData:
    def test_json_ld_parse_list(self):
        html = '<script type="application/ld+json">[{"@type": "Product"}, {"@type": "Article"}]</script>'
        objs = _json_ld_objects(html)
        assert len(objs) == 2

    def test_valid_product(self):
        html = '<script type="application/ld+json">{"@type": "Product", "name": "Widget", "offers": {}}</script>'
        r = validate_structured_data("https://x.com", html)
        assert r["valid"] is True
        assert r["types_present"] == ["Product"]

    def test_missing_required(self):
        html = '<script type="application/ld+json">{"@type": "Article", "headline": "Hi"}</script>'
        r = validate_structured_data("https://x.com", html)
        assert r["valid"] is False
        assert "author" in r["missing_required"]["Article"]

    def test_faq_deprecated_ignored(self):
        html = '<script type="application/ld+json">{"@type": "FAQPage", "mainEntity": []}</script>'
        r = validate_structured_data("https://x.com", html)
        assert r["valid"] is False
        assert "FAQPage (deprecated - ignored)" in r["types_present"]
        assert "FAQPage" not in r["invalid_types"]

    def test_bad_json_ignored(self):
        html = '<script type="application/ld+json">{not json}</script>'
        r = validate_structured_data("https://x.com", html)
        assert r["has_structured_data"] is False


class TestMisc:
    def test_grade_boundaries(self):
        assert _grade(95) == "A"
        assert _grade(85) == "B"
        assert _grade(75) == "C"
        assert _grade(65) == "D"
        assert _grade(40) == "F"

    def test_orphan_norm(self):
        assert _norm("https://x.com/Team/") == "https://x.com/team"
        assert _norm("https://x.com/a/") == _norm("https://x.com/a")
