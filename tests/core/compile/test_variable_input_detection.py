"""Tests for variable input type auto-detection.

When input is 'auto' (or omitted), the system infers input type from
authored fields: options → select, min/max/step → slider, bool default →
checkbox, list default → multiselect, hidden with no signals → text, etc.
"""

from dbt_charts.core.compile.compiler import compile
from dbt_charts.core.compile.models.variable.authored import (
    Variable,
    VariableOptions,
)
from dbt_charts.core.compile.normalize.variables import detect_variable_input_type


class TestDetectVariableInputType:
    """Unit tests for detect_variable_input_type."""

    def test_static_options_infers_select(self):
        var = Variable(options=VariableOptions(static=["A", "B", "C"]))
        assert detect_variable_input_type(var) == "select"

    def test_query_options_infers_select(self):
        var = Variable(options=VariableOptions(query="my_query"))
        assert detect_variable_input_type(var) == "select"

    def test_options_with_list_default_infers_multiselect(self):
        var = Variable(
            options=VariableOptions(static=["A", "B", "C"]),
            default=["A", "B"],
        )
        assert detect_variable_input_type(var) == "multiselect"

    def test_list_default_without_options_infers_multiselect(self):
        var = Variable(default=["a", "b"])
        assert detect_variable_input_type(var) == "multiselect"

    def test_min_max_infers_slider(self):
        var = Variable(min=0, max=100)
        assert detect_variable_input_type(var) == "slider"

    def test_step_alone_infers_slider(self):
        var = Variable(step=5)
        assert detect_variable_input_type(var) == "slider"

    def test_min_only_infers_slider(self):
        var = Variable(min=0)
        assert detect_variable_input_type(var) == "slider"

    def test_bool_default_infers_checkbox(self):
        var = Variable(default=True)
        assert detect_variable_input_type(var) == "checkbox"

    def test_bool_false_default_infers_checkbox(self):
        var = Variable(default=False)
        assert detect_variable_input_type(var) == "checkbox"

    def test_not_visible_no_signals_infers_text(self):
        var = Variable(visible=False)
        assert detect_variable_input_type(var) == "text"

    def test_not_visible_with_options_infers_select(self):
        """visible=False doesn't override options signal."""
        var = Variable(visible=False, options=VariableOptions(static=["A", "B"]))
        assert detect_variable_input_type(var) == "select"

    def test_column_only_infers_select(self):
        var = Variable(column="category")
        assert detect_variable_input_type(var) == "select"

    def test_bare_variable_infers_text(self):
        """No signals at all → text."""
        var = Variable()
        assert detect_variable_input_type(var) == "text"

    def test_explicit_input_not_changed(self):
        """When input is explicitly set (not auto), detection is skipped."""
        var = Variable(input="radio", options=VariableOptions(static=["A", "B"]))
        # Detection should return the explicit type unchanged
        assert detect_variable_input_type(var) == "radio"

    def test_explicit_slider_not_changed(self):
        var = Variable(input="slider", min=0, max=100)
        assert detect_variable_input_type(var) == "slider"


class TestDetectVariableInputTypeInCompile:
    """Integration tests: auto-detection through compile()."""

    def test_compile_omitted_input_with_options(self):

        yaml_content = """
title: Test
variables:
  category:
    options:
      static: ["A", "B", "C"]
    default: "A"
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.board.variables["category"].input == "select"

    def test_compile_omitted_input_with_slider_fields(self):

        yaml_content = """
title: Test
variables:
  volume:
    min: 0
    max: 100
    step: 5
    default: 50
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.board.variables["volume"].input == "slider"

    def test_compile_omitted_input_with_bool_default(self):

        yaml_content = """
title: Test
variables:
  show_totals:
    default: true
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.board.variables["show_totals"].input == "checkbox"

    def test_compile_omitted_input_with_list_default(self):

        yaml_content = """
title: Test
variables:
  tags:
    options:
      static: ["a", "b", "c"]
    default: ["a", "b"]
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.board.variables["tags"].input == "multiselect"

    def test_compile_explicit_input_preserved(self):

        yaml_content = """
title: Test
variables:
  category:
    input: radio
    options:
      static: ["A", "B", "C"]
    default: "A"
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.board.variables["category"].input == "radio"


class TestInputAutoDetectedFlag:
    """Verify input_auto_detected is set correctly during compilation."""

    def test_auto_detected_select_gets_flag(self):
        yaml_content = """
title: Test
variables:
  category:
    options:
      static: ["A", "B", "C"]
    default: "A"
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success
        assert result.board.variables["category"].input_auto_detected is True

    def test_auto_detected_checkbox_does_not_get_flag(self):
        """Strong structural signals (bool → checkbox) should not be flagged."""
        yaml_content = """
title: Test
variables:
  show_totals:
    default: true
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success
        assert result.board.variables["show_totals"].input == "checkbox"
        assert result.board.variables["show_totals"].input_auto_detected is False

    def test_explicit_input_does_not_get_flag(self):
        yaml_content = """
title: Test
variables:
  category:
    input: radio
    options:
      static: ["A", "B"]
    default: "A"
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success
        assert result.board.variables["category"].input_auto_detected is False

    def test_auto_detected_multiselect_does_not_get_flag(self):
        """Multiselect has multi-value semantics that can't map to refined types."""
        yaml_content = """
title: Test
variables:
  tags:
    options:
      static: ["a", "b", "c"]
    default: ["a", "b"]
queries:
  test:
    type: values
    rows:
      - {x: 1}
charts:
  chart1:
    query: test
    type: table
rows:
  - chart1
"""
        result = compile(yaml_content)
        assert result.success
        assert result.board.variables["tags"].input == "multiselect"
        assert result.board.variables["tags"].input_auto_detected is False
