"""Tests for `dct playground`.

`dct playground` opens the hosted playground (https://play.dbtcharts.com) in
the user's browser and always prints the URL too, since a browser-open call
doesn't reliably signal success over SSH/headless sessions.
"""

from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from dbt_charts.cli.main import PLAYGROUND_URL, app

runner = CliRunner()


def test_playground_opens_and_prints_hosted_url() -> None:
    assert PLAYGROUND_URL == "https://play.dbtcharts.com"

    with patch("webbrowser.open") as mock_open:
        result = runner.invoke(app, ["playground"])

    assert result.exit_code == 0, result.output
    mock_open.assert_called_once_with(PLAYGROUND_URL)
    assert PLAYGROUND_URL in result.output


def test_playground_prints_url_even_when_browser_open_fails() -> None:
    with patch("webbrowser.open", side_effect=OSError("no display")):
        result = runner.invoke(app, ["playground"])

    assert result.exit_code == 0, result.output
    assert PLAYGROUND_URL in result.output
