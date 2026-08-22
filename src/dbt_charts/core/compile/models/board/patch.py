"""Board patch model: all-optional overlay used by the merge engine.

``BoardPatch`` is the all-optional counterpart to ``AuthoredBoard``, generated
mechanically by ``build_patch_model``.  Every field that carries a ``Merge``
annotation on ``AuthoredBoard`` has that annotation forwarded here, so
``merge_patches`` can read the strategy directly from the patch model's field
metadata without consulting the canonical model.

``EMPTY_PATCH`` is the all-None, no-fields-set sentinel used as the accumulator
base in ``merge_extends`` / ``merge_metas`` before any fragment is layered on.
"""

from __future__ import annotations

from dbt_charts.core.compile.models.board.authored import (
    AuthoredBoard,
    _BoardDesugarMixin,
)
from dbt_charts.core.compile.models.factories import (
    _PatchBase,
    build_patch_model_ext,
)


class _BoardPatchBase(_PatchBase, _BoardDesugarMixin):
    """Base for BoardPatch: inherits extra="forbid" from _PatchBase and
    theme→extends desugaring from _BoardDesugarMixin.
    """


BoardPatch = build_patch_model_ext(AuthoredBoard, base_cls=_BoardPatchBase)

# All-None sentinel: no fields set, safe as the identity element for merge_patches.
EMPTY_PATCH: BoardPatch = BoardPatch.model_construct()  # type: ignore[valid-type]
