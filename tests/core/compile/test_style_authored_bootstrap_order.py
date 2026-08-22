"""Regression coverage for the forward-ref bootstrap order in
compile/models/style/authored/_base.py.

`_base` injects authored types into `style.theme`'s module globals and
rebuilds the theme chart-style classes so forward refs (e.g.
EndpointLabelsConfig) resolve, before any per-family submodule
(area/bar/kpi/line/pie/...) runs its own `build_patch_model(FooChartStyle)`.
If that ordering regresses, the per-family patch model's nested field
annotation is built from the *unresolved* ForwardRef instead of the real
patch type — this pins the correct, resolved shape.
"""

from __future__ import annotations

import pytest

from dbt_charts.core.compile.models.style.authored import (
    AreaChartStylePatch,
    BarChartStylePatch,
    EndpointLabelsConfigPatch,
    LineChartStylePatch,
)


@pytest.mark.parametrize(
    "patch_cls", [AreaChartStylePatch, LineChartStylePatch, BarChartStylePatch]
)
def test_endpoint_labels_forward_ref_is_resolved(patch_cls):
    field = patch_cls.model_fields["endpoint_labels"]
    resolved_types = set(getattr(field.annotation, "__args__", (field.annotation,)))
    assert EndpointLabelsConfigPatch in resolved_types, (
        f"{patch_cls.__name__}.endpoint_labels did not resolve to "
        f"EndpointLabelsConfigPatch (got {field.annotation!r}) — the _base "
        "forward-ref bootstrap likely ran after this family's build_patch_model()."
    )
