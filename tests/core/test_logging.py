"""Tests for logging configuration and behavior."""

import logging

import pytest


class TestLoggingConfiguration:
    """Tests for dbt charts logging setup."""

    def test_package_logger_exists(self) -> None:
        """Test that the dbt_charts package logger is configured."""
        import dbt_charts

        assert logging.getLogger("dbt_charts") is dbt_charts.logger

    def test_package_logger_has_null_handler(self) -> None:
        """Test that package logger has NullHandler to prevent warnings."""
        import dbt_charts

        assert any(
            isinstance(h, logging.NullHandler) for h in dbt_charts.logger.handlers
        )

    def test_logger_can_log_at_all_levels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that the logger can emit messages at all levels."""
        test_logger = logging.getLogger("dbt_charts.test")

        with caplog.at_level(logging.DEBUG, logger="dbt_charts.test"):
            test_logger.debug("debug message")
            test_logger.info("info message")
            test_logger.warning("warning message")
            test_logger.error("error message")

        assert "debug message" in caplog.text
        assert "info message" in caplog.text
        assert "warning message" in caplog.text
        assert "error message" in caplog.text
