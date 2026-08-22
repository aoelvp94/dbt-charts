"""Tests for `dct docs errors` / `dct docs warnings` list and detail verbs.

Parametrized over both CLI verbs: they are two filtered views over the
one diagnostic registry, so their list/detail/json/error-handling behavior is
identical modulo `level`. Cross-level resolution (a code typed under the
"wrong" verb) gets its own dedicated tests.
"""

from __future__ import annotations

import json
import re
from typing import Literal

import pytest
from typer.testing import CliRunner

from dbt_charts.agent_api.diagnostics import REGISTRY
from dbt_charts.cli.main import app

runner = CliRunner()

_Level = Literal["error", "warning"]

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_TOPIC_FOR_LEVEL: dict[_Level, str] = {"error": "errors", "warning": "warnings"}
_KNOWN_CODE: dict[_Level, str] = {
    "error": "ERR-NO-LAYOUT",
    "warning": "WARN-REDUNDANT-ENCODING",
}
_KNOWN_CODE_SUBSTRING: dict[_Level, str] = {"error": "layout", "warning": "redundant"}


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _all_codes(level: _Level) -> list[str]:
    return sorted(REGISTRY.codes(level=level))


@pytest.fixture(params=["error", "warning"])
def level(request: pytest.FixtureRequest) -> _Level:
    return request.param


@pytest.fixture
def topic(level: _Level) -> str:
    return _TOPIC_FOR_LEVEL[level]


class TestDocsDiagnosticsList:
    """dct docs errors|warnings — list all registered codes with one-line descriptions."""

    def test_exit_zero(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic])
        assert result.exit_code == 0, result.output

    def test_every_registered_code_appears(self, topic: str, level: _Level) -> None:
        result = runner.invoke(app, ["docs", topic])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        for code in _all_codes(level):
            assert code in text, f"Expected {code!r} in list output:\n{text}"

    def test_one_line_description_from_summary_for(
        self, topic: str, level: _Level
    ) -> None:
        """Each code's row includes the CLI-rendered summary (`_summary_for`).

        `_summary_for` returns the authored `summary` when a code's doc trips
        the sentence-boundary guard (e.g. an unclosed parenthetical), else the
        derived first sentence of `doc` — never `detect.__doc__` (which would
        start with 'Return one RenderWarning per…').
        """
        from dbt_charts.agent_api.diagnostics import _summary_for

        result = runner.invoke(app, ["docs", topic])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        for dc in REGISTRY.all(level=level):
            summary = _summary_for(dc)
            assert summary in text, (
                f"Expected doc summary for {dc.code!r} "
                f"({summary!r}) in list output:\n{text}"
            )
            assert not summary.startswith("Return "), (
                f"Summary for {dc.code!r} looks like detect.__doc__ jargon: {summary!r}"
            )

    def test_codes_appear_sorted(self, topic: str, level: _Level) -> None:
        result = runner.invoke(app, ["docs", topic])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        codes = _all_codes(level)
        positions = [text.index(code) for code in codes]
        assert positions == sorted(positions), (
            f"Codes are not in sorted order in list output. "
            f"Codes: {codes}, positions: {positions}"
        )


class TestDocsDiagnosticsDetail:
    """dct docs errors|warnings <CODE> — prints the code's full documentation."""

    def test_known_code_exits_zero(self, topic: str, level: _Level) -> None:
        result = runner.invoke(app, ["docs", topic, _KNOWN_CODE[level]])
        assert result.exit_code == 0, result.output

    def test_doc_appears_in_output(self, topic: str, level: _Level) -> None:
        result = runner.invoke(app, ["docs", topic, _KNOWN_CODE[level]])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        assert _KNOWN_CODE_SUBSTRING[level] in text.lower(), (
            f"Expected doc content in detail output:\n{text}"
        )

    def test_code_is_case_insensitive(self, topic: str, level: _Level) -> None:
        code = _KNOWN_CODE[level]
        result_upper = runner.invoke(app, ["docs", topic, code])
        result_lower = runner.invoke(app, ["docs", topic, code.lower()])
        assert result_upper.exit_code == 0
        assert result_lower.exit_code == 0
        assert _plain(result_upper.output) == _plain(result_lower.output)

    def test_all_registered_codes_resolve(self, topic: str, level: _Level) -> None:
        for dc in REGISTRY.all(level=level):
            result = runner.invoke(app, ["docs", topic, dc.code])
            assert result.exit_code == 0, (
                f"dct docs {topic} {dc.code} exited {result.exit_code}:\n"
                f"{result.output}"
            )


class TestDocsDiagnosticsUnknownCode:
    """dct docs errors|warnings <UNKNOWN> exits non-zero with a clear error."""

    def test_unknown_code_exits_nonzero(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "UNKNOWN_CODE_XYZ"])
        assert result.exit_code != 0, (
            f"Expected non-zero exit for unknown code; got 0. Output:\n{result.output}"
        )

    def test_unknown_code_error_message_is_clear(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "UNKNOWN_CODE_XYZ"])
        combined = (result.output or "") + (result.stderr or "")
        assert "UNKNOWN_CODE_XYZ" in combined, (
            f"Expected 'UNKNOWN_CODE_XYZ' in error output:\n{combined}"
        )

    def test_unknown_code_suggests_valid_codes(self, topic: str, level: _Level) -> None:
        """Error output should list or hint at valid codes."""
        result = runner.invoke(app, ["docs", topic, "UNKNOWN_CODE_XYZ"])
        combined = (result.output or "") + (result.stderr or "")
        codes = _all_codes(level)
        has_hint = any(code in combined for code in codes)
        assert has_hint, (
            f"Expected at least one valid code in error output as a hint. "
            f"Got:\n{combined}"
        )


class TestDocsHelpAdvertisesDiagnostics:
    """dct docs --help mentions both diagnostic sub-verbs."""

    def test_errors_and_warnings_in_docs_help(self) -> None:
        result = runner.invoke(app, ["docs", "--help"])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        assert "errors" in text, f"Expected 'errors' in dct docs --help output:\n{text}"
        assert "warnings" in text, (
            f"Expected 'warnings' in dct docs --help output:\n{text}"
        )


class TestDocsDiagnosticsJson:
    """dct docs errors|warnings --json emits valid JSON with the expected schema."""

    def test_list_json_schema(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["mode"] == "diagnostic_list"
        codes = data["codes"]
        assert isinstance(codes, list)
        assert len(codes) > 0
        for entry in codes:
            assert set(entry.keys()) >= {"code", "summary"}

    def test_list_json_sorted(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "--json"])
        data = json.loads(result.output)
        codes = [e["code"] for e in data["codes"]]
        assert codes == sorted(codes)

    def test_detail_json_schema(self, topic: str, level: _Level) -> None:
        code = _KNOWN_CODE[level]
        result = runner.invoke(app, ["docs", topic, code, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["mode"] == "diagnostic_detail"
        detail = data["detail"]
        assert set(detail.keys()) >= {"code", "level", "summary", "doc"}
        assert detail["code"] == code

    def test_unknown_code_json_exits_nonzero(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "NONEXISTENT_XYZ", "--json"])
        assert result.exit_code != 0
        data = json.loads(result.output)
        assert data["success"] is False
        assert "NONEXISTENT_XYZ" in data["errors"][0]


class TestDocsDiagnosticsTopicIndex:
    """dct docs (bare) lists both diagnostic verbs in the topic index."""

    def test_errors_and_warnings_rows_in_plain_index(self) -> None:
        result = runner.invoke(app, ["docs"])
        assert result.exit_code == 0, result.output
        text = _plain(result.output)
        assert "dct docs errors" in text, (
            f"Expected 'dct docs errors' in topic index output:\n{text}"
        )
        assert "dct docs warnings" in text, (
            f"Expected 'dct docs warnings' in topic index output:\n{text}"
        )


class TestDocsCodeArgLeaks:
    """code arg is rejected for non-diagnostic topics."""

    def test_code_with_non_diagnostic_topic_exits_nonzero(self) -> None:
        result = runner.invoke(app, ["docs", "board", "extra-arg"])
        assert result.exit_code != 0

    def test_code_with_non_diagnostic_topic_has_clear_error(self) -> None:
        result = runner.invoke(app, ["docs", "board", "extra-arg"])
        combined = (result.output or "") + (result.stderr or "")
        assert "errors" in combined.lower() or "warnings" in combined.lower(), (
            f"Expected mention of 'errors'/'warnings' in error for "
            f"code-on-non-diagnostic-topic:\n{combined}"
        )


class TestDocsDiagnosticsSearchRejected:
    """dct docs errors|warnings --search is rejected with exit code 2."""

    def test_search_with_topic_exits_two(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "--search", "thin bars"])
        assert result.exit_code == 2, (
            f"Expected exit code 2 (BadParameter) for {topic} --search; "
            f"got {result.exit_code}. Output:\n{result.output}"
        )

    def test_search_with_topic_error_mentions_search(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "--search", "thin bars"])
        combined = (result.output or "") + (result.stderr or "")
        assert "--search" in combined or "search" in combined.lower(), (
            f"Expected mention of 'search' in error:\n{combined}"
        )

    def test_search_with_topic_error_mentions_topic(self, topic: str) -> None:
        result = runner.invoke(app, ["docs", topic, "--search", "thin bars"])
        combined = (result.output or "") + (result.stderr or "")
        assert topic in combined.lower(), (
            f"Expected mention of {topic!r} in error:\n{combined}"
        )


class TestDocsDiagnosticsDetailRendering:
    """Detail output does not double-print code; routes through markdown."""

    def test_code_prefix_not_duplicated(self, topic: str, level: _Level) -> None:
        """Code string should not appear twice on the same line in detail output."""
        code = _KNOWN_CODE[level]
        result = runner.invoke(app, ["docs", topic, code])
        assert result.exit_code == 0
        text = _plain(result.output)
        assert f"[{code}]" not in text, (
            f"Bracketed code prefix appeared in detail output:\n{text}"
        )


class TestDocsDiagnosticsCrossLevelResolution:
    """A code typed under the other verb still resolves and says so — never
    'unknown code' for a code we ship (Plan item, replaces the old warning-only
    lookup's rejection behavior)."""

    def test_error_code_under_warnings_verb_still_resolves(self) -> None:
        result = runner.invoke(app, ["docs", "warnings", "ERR-NO-LAYOUT"])
        assert result.exit_code == 0, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "ERR-NO-LAYOUT" in combined
        assert "error" in combined.lower()

    def test_warning_code_under_errors_verb_still_resolves(self) -> None:
        result = runner.invoke(app, ["docs", "errors", "WARN-REDUNDANT-ENCODING"])
        assert result.exit_code == 0, result.output
        combined = (result.output or "") + (result.stderr or "")
        assert "WARN-REDUNDANT-ENCODING" in combined
        assert "warning" in combined.lower()

    def test_cross_level_json_still_succeeds(self) -> None:
        result = runner.invoke(app, ["docs", "warnings", "ERR-NO-LAYOUT", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert data["detail"]["level"] == "error"
