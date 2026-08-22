"""Tests for profiler navigation link markup in templates.

M2: _build_nav_links and _column_template_for_type were removed from
renderer.py as part of the cache-gated renderer var cleanup. Nav-link
generation (column name → drill-in template) is deferred to M3.

The tests that remain cover structural invariants: templates must contain
the correct back-link and cross-link URL prefixes so server routing works.
"""


class TestTemplateNavContent:
    """Tests that templates contain navigation link markup."""

    def _load_template(self, name: str) -> str:
        from importlib.resources import files

        return (
            files("dbt_charts.core.inspect.templates")
            .joinpath(f"{name}.yml")
            .read_text()
        )

    def test_model_template_has_quality_link(self) -> None:
        content = self._load_template("model")
        assert "/inspect/quality/" in content

    def test_numeric_column_has_back_link(self) -> None:
        content = self._load_template("numeric_column")
        assert "/inspect/model/" in content

    def test_string_column_has_back_link(self) -> None:
        content = self._load_template("string_column")
        assert "/inspect/model/" in content

    def test_date_column_has_back_link(self) -> None:
        content = self._load_template("date_column")
        assert "/inspect/model/" in content

    def test_categorical_column_has_back_link(self) -> None:
        content = self._load_template("categorical_column")
        assert "/inspect/model/" in content

    def test_quality_has_back_link(self) -> None:
        content = self._load_template("quality")
        assert "/inspect/model/" in content
