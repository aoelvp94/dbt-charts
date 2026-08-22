"""Tests for dbt_charts.agent_api.skills.search_skills."""

from __future__ import annotations

import pytest

from dbt_charts.agent_api.skills import search_skills


class TestSearchSkills:
    def test_empty_query_raises(self) -> None:
        with pytest.raises(ValueError, match="query"):
            search_skills("")

    def test_whitespace_only_query_raises(self) -> None:
        with pytest.raises(ValueError, match="query"):
            search_skills("   ")

    def test_no_hits_returns_empty(self) -> None:
        result = search_skills("zzznevermatch")
        assert result.success is True
        assert result.hits == []

    def test_name_substring_returns_hit_with_full_score(self) -> None:
        result = search_skills("kpi-row")
        names = [h.name for h in result.hits]
        assert "kpi-row" in names
        kpi = next(h for h in result.hits if h.name == "kpi-row")
        assert kpi.score == pytest.approx(1.0)

    def test_description_match_scores_lower_than_name_match(self) -> None:
        # "drill" is in the name `drill-down-link` (score 1.0)
        # and may or may not be in other descriptions/bodies — just check ordering.
        result = search_skills("drill")
        assert result.hits, "expected at least one hit"
        # First hit should be the name match.
        assert result.hits[0].name == "drill-down-link"
        assert result.hits[0].score == pytest.approx(1.0)

    def test_limit_honored(self) -> None:
        # "a" appears in many descriptions; limit=2 should cap output.
        result = search_skills("a", limit=2)
        assert len(result.hits) <= 2

    def test_hits_include_kind_and_has_examples(self) -> None:
        result = search_skills("kpi-row")
        kpi = next(h for h in result.hits if h.name == "kpi-row")
        assert kpi.kind == "pattern"
        assert kpi.has_examples is True

    def test_results_sorted_by_score_desc_then_name_asc(self) -> None:
        result = search_skills("dashboard")
        # Confirm score is non-increasing across hits.
        scores = [h.score for h in result.hits]
        assert scores == sorted(scores, reverse=True)
        # Within same score, names are alphabetical.
        for i in range(len(result.hits) - 1):
            if result.hits[i].score == result.hits[i + 1].score:
                assert result.hits[i].name < result.hits[i + 1].name
