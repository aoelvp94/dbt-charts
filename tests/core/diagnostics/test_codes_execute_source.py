"""Tests for ERR-SOURCE-* allowlist error codes."""

from __future__ import annotations


class TestCodesExecuteSource:
    def test_codes_registered(self) -> None:
        from dbt_charts.core.diagnostics import REGISTRY
        from dbt_charts.core.diagnostics.codes_compile import (
            ERR_SOURCE_INLINE_FORBIDDEN,
        )
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_CROSS_FILE_FORBIDDEN,
            ERR_SOURCE_INVALID_TYPE,
            ERR_SOURCE_MISSING_TYPE,
        )

        assert (
            REGISTRY.get("ERR-SOURCE-INLINE-FORBIDDEN") is ERR_SOURCE_INLINE_FORBIDDEN
        )
        assert (
            REGISTRY.get("ERR-SOURCE-CROSS-FILE-FORBIDDEN")
            is ERR_SOURCE_CROSS_FILE_FORBIDDEN
        )
        assert REGISTRY.get("ERR-SOURCE-INVALID-TYPE") is ERR_SOURCE_INVALID_TYPE
        assert REGISTRY.get("ERR-SOURCE-MISSING-TYPE") is ERR_SOURCE_MISSING_TYPE

    def test_doc_url_and_topic_present(self) -> None:
        from dbt_charts.core.diagnostics.codes_compile import (
            ERR_SOURCE_INLINE_FORBIDDEN,
        )
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_CROSS_FILE_FORBIDDEN,
            ERR_SOURCE_INVALID_TYPE,
            ERR_SOURCE_MISSING_TYPE,
        )

        for code in (
            ERR_SOURCE_INLINE_FORBIDDEN,
            ERR_SOURCE_CROSS_FILE_FORBIDDEN,
            ERR_SOURCE_INVALID_TYPE,
            ERR_SOURCE_MISSING_TYPE,
        ):
            assert code.doc_url, f"{code.code} missing doc_url"
            assert code.docs_topic == "queries", f"{code.code} wrong docs_topic"

    def test_inline_forbidden_message_mentions_rule(self) -> None:
        from dbt_charts.core.diagnostics.codes_compile import (
            ERR_SOURCE_INLINE_FORBIDDEN,
        )

        msg = ERR_SOURCE_INLINE_FORBIDDEN.message_template.format(
            query_name="q1",
            offending_value="{type: duckdb, path: /tmp/db}",
        )
        assert "inline source" in msg.lower() or "connection parameters" in msg.lower()

    def test_cross_file_forbidden_message_mentions_anchor(self) -> None:
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_CROSS_FILE_FORBIDDEN,
        )

        msg = ERR_SOURCE_CROSS_FILE_FORBIDDEN.message_template.format(
            offending_value="other.yaml#x",
        )
        assert "#" in msg
        assert "cross-file" in msg.lower() or "cross_file" in msg.lower()

    def test_invalid_type_message_lists_valid_types(self) -> None:
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_INVALID_TYPE,
        )

        msg = ERR_SOURCE_INVALID_TYPE.message_template.format(
            offending_value="oracl",
            available="bigquery,duckdb,snowflake",
        )
        assert "oracl" in msg
        assert "type" in msg.lower() or "unknown" in msg.lower()

    def test_missing_type_message_mentions_type_field(self) -> None:
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_MISSING_TYPE,
        )

        msg = ERR_SOURCE_MISSING_TYPE.message_template.format(
            offending_value="{path: /tmp/db}",
        )
        assert "type" in msg

    def test_inline_forbidden_has_no_hint_generator(self) -> None:
        """Codes whose template already enumerates the valid set carry no hint.

        ERR-SOURCE-INVALID-TYPE is in this group: its subject is a source
        *type* drawn from a closed five-name enum the message already prints,
        not a source *name*, so `suggest_close_source` never fit it.
        """
        from dbt_charts.core.diagnostics.codes_compile import (
            ERR_SOURCE_INLINE_FORBIDDEN,
        )
        from dbt_charts.core.diagnostics.codes_execute import (
            ERR_SOURCE_CROSS_FILE_FORBIDDEN,
            ERR_SOURCE_INVALID_TYPE,
            ERR_SOURCE_MISSING_TYPE,
        )

        assert ERR_SOURCE_INLINE_FORBIDDEN.hint_generator is None
        assert ERR_SOURCE_CROSS_FILE_FORBIDDEN.hint_generator is None
        assert ERR_SOURCE_MISSING_TYPE.hint_generator is None
        assert ERR_SOURCE_INVALID_TYPE.hint_generator is None
