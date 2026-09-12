"""A URL's query string becomes variable values by one rule, shared by every server.

A list-valued variable travels as a repeated key — `?region=west&region=east` —
the way an HTML form sends a `<select multiple>`, so a link is hand-writable and
carries no JSON. Both servers used to take `dict(params)`, which keeps only the
last repeat, so the standard form silently dropped every value but one.
"""

from dbt_charts.core.compile.template.variables import (
    parse_variable_json_strings,
    variables_from_query_pairs,
)


def test_a_repeated_key_is_a_list_in_order() -> None:
    pairs = [("region", "west"), ("priority", "high"), ("region", "east")]

    assert parse_variable_json_strings(variables_from_query_pairs(pairs)) == {
        "region": ["west", "east"],
        "priority": "high",
    }


def test_the_repeated_form_lands_where_the_json_form_always_did() -> None:
    """Past this boundary nothing can tell which form a link used."""
    repeated = variables_from_query_pairs([("region", "west"), ("region", "east")])
    json_form = variables_from_query_pairs([("region", '["west", "east"]')])

    assert repeated == json_form == {"region": '["west", "east"]'}


def test_a_single_key_stays_a_scalar() -> None:
    assert variables_from_query_pairs([("region", "west")]) == {"region": "west"}


def test_an_explicit_empty_survives() -> None:
    """`?region=` means "no value", distinct from the key being absent."""
    assert variables_from_query_pairs([("region", "")]) == {"region": ""}


def test_a_member_may_contain_any_delimiter() -> None:
    """The reason the previous encoding was JSON — each value is its own param now."""
    pairs = [("city", "New York, NY"), ("city", "Portland, OR")]

    assert parse_variable_json_strings(variables_from_query_pairs(pairs)) == {
        "city": ["New York, NY", "Portland, OR"]
    }
