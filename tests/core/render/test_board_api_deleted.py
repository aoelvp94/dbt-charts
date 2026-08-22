# Fails today because: dbt_charts.core.render.board_api still exists as a module and
# importing the dotted path resolves successfully (no ModuleNotFoundError).
import importlib

import pytest


def test_core_render_board_api_module_is_deleted() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("dbt_charts.core.render.board_api")
