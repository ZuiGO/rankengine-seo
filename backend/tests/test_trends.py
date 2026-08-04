"""Unit tests for trend delta computation (pure functions, no DB)."""

from backend.routes.trends import compute_deltas


class TestComputeDeltas:
    def test_numeric_diffs(self):
        d = compute_deltas(
            {"health_score": 60, "broken_link_count": 3, "total_pages": 10, "avg_cwv_score": 40, "keyword_ranked": 5},
            {"health_score": 70, "broken_link_count": 8, "total_pages": 12, "avg_cwv_score": 50, "keyword_ranked": 3},
        )
        assert d["health_score"] == 10.0
        assert d["broken_link_count"] == 5.0
        assert d["total_pages"] == 2.0
        assert d["avg_cwv_score"] == 10.0
        assert d["keyword_ranked"] == -2.0

    def test_missing_values_none(self):
        d = compute_deltas({"health_score": 60}, {"broken_link_count": 8})
        assert d["health_score"] is None
        assert d["broken_link_count"] is None
        assert d["total_pages"] is None

    def test_first_point_has_no_prev(self):
        d = compute_deltas(None, {"health_score": 70})
        assert d["health_score"] is None

    def test_non_numeric_ignored(self):
        d = compute_deltas({"health_score": "A"}, {"health_score": 70})
        assert d["health_score"] is None

    def test_rounds_to_two_decimals(self):
        d = compute_deltas({"avg_cwv_score": 33.333}, {"avg_cwv_score": 44.444})
        assert d["avg_cwv_score"] == 11.11
