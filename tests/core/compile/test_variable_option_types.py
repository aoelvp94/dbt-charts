"""Static option lists and `data_type` are the type contract for a choice
input's values, so a list that cannot name one type is refused at authoring."""

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.compiler import compile
from dbt_charts.core.compile.errors import CompilationError
from dbt_charts.core.compile.models.variable.authored import (
    Variable,
    VariableOptions,
)
from dbt_charts.core.compile.normalize.variables import (
    validate_choice_type,
    validate_variable_value,
)
from dbt_charts.core.compile.template.variables import coerce_variable_values


def test_mixed_static_option_types_are_refused() -> None:
    with pytest.raises(ValidationError, match="one type"):
        VariableOptions(static=[2023, "all"])


@pytest.mark.parametrize("static", [[1, 2.5], ["a", "b"], [1, 2]])
def test_homogeneous_static_options_are_accepted(static: list[object]) -> None:
    assert VariableOptions.model_validate({"static": static}).static == static


def test_unknown_data_type_is_refused() -> None:
    with pytest.raises(ValidationError):
        Variable.model_validate({"input": "select", "data_type": "integer"})


def test_data_type_number_with_word_options_is_refused_at_compile() -> None:
    """Through the pipeline, and without a default: a query-driven choice
    usually has none, and the gate must not depend on one."""
    result = compile(
        "variables:\n"
        "  v:\n"
        "    input: select\n"
        "    data_type: number\n"
        "    options:\n"
        "      static: [north, south]\n"
        "queries:\n"
        "  q:\n"
        "    columns: [n]\n"
        "    values: [[1]]\n"
        "charts:\n"
        "  c:\n"
        "    type: kpi\n"
        "    query: q\n"
        "    value: n\n"
    )
    assert not result.success
    assert [e.code for e in result.errors] == ["ERR-VALIDATION-FIELD"]
    assert "data_type" in result.errors[0].message


@pytest.mark.parametrize("data_type", ["string", "array"])
def test_inert_data_type_keeps_numeric_options_as_strings(data_type: str) -> None:
    var = Variable.model_validate(
        {
            "input": "select",
            "data_type": data_type,
            "options": {"static": [90210, 10001]},
        }
    )
    assert coerce_variable_values({"z": "90210"}, {"z": var})["z"] == "90210"


def test_an_unset_string_select_is_none() -> None:
    var = Variable.model_validate(
        {"input": "select", "options": {"static": ["a", "b"]}}
    )
    assert coerce_variable_values({"s": ""}, {"s": var})["s"] is None


def test_data_type_is_inert_outside_choice_inputs() -> None:
    """A number input with a stray `data_type: date` is not a choice; the
    option list is not its contract and must not refuse the board."""
    var = Variable.model_validate(
        {"input": "number", "data_type": "date", "options": {"static": ["2024-01-01"]}}
    )
    validate_choice_type("v", var)


def test_boolean_data_type_converts_the_sent_text() -> None:
    var = Variable.model_validate({"input": "select", "data_type": "boolean"})
    assert coerce_variable_values({"b": "true"}, {"b": var})["b"] is True


def test_data_type_number_with_a_word_default_is_refused_at_compile() -> None:
    var = Variable.model_validate(
        {"input": "select", "data_type": "number", "options": {"query": "q"}}
    )
    with pytest.raises(CompilationError, match="numeric"):
        validate_variable_value("v", var, "a")


def test_data_type_boolean_default_is_accepted() -> None:
    var = Variable.model_validate({"input": "select", "data_type": "boolean"})
    validate_variable_value("v", var, False)


def test_mixed_static_list_is_refused_at_compile_naming_the_field() -> None:
    result = compile(
        "variables:\n"
        "  v:\n"
        "    input: select\n"
        "    options:\n"
        "      static: [2023, 2024, All]\n"
        "queries:\n"
        "  q:\n"
        "    columns: [n]\n"
        "    values: [[1]]\n"
        "charts:\n"
        "  c:\n"
        "    type: kpi\n"
        "    query: q\n"
        "    value: n\n"
    )
    assert not result.success
    assert [e.code for e in result.errors] == ["ERR-VALIDATION-FIELD"]
    assert "options.static" in result.errors[0].message
