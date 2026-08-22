"""Tests for the dbt-charts/scripts/check_models.py model-convention checker.

Each rule gets at least one passing and one failing fixture, asserted via the
checker's return code and violation messages.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

from .._paths import DBT_CHARTS_DIR

# Add scripts/ to path so we can import the checker directly.
_SCRIPTS_DIR = DBT_CHARTS_DIR / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
from check_models import check_file  # noqa: E402


def _tmp_file(tmp_path: Path, name: str, source: str) -> Path:
    """Write source to a .py file under the models-tree-like path and return it."""
    # checker only applies Rule 5 to specific paths; use a neutral path for others.
    p = tmp_path / name
    p.write_text(textwrap.dedent(source))
    return p


# ---------------------------------------------------------------------------
# Rule 1 — bare-dict model_config
# ---------------------------------------------------------------------------


class TestRule1BareDict:
    def test_passes_with_configdict(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "good.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class MyModel(BaseModel):
                model_config = ConfigDict(extra="forbid")
                x: int
            """,
        )
        violations = check_file(f)
        assert not [v for v in violations if v.rule == 1]

    def test_fails_with_bare_dict(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "bad.py",
            """\
            from pydantic import BaseModel

            class MyModel(BaseModel):
                model_config = {"extra": "forbid"}
                x: int
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 1]
        assert len(violations) == 1
        assert "bare dict" in violations[0].message

    def test_bare_dict_message_names_class(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "named.py",
            """\
            from pydantic import BaseModel

            class FooStyle(BaseModel):
                model_config = {"extra": "allow"}
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 1]
        assert any("FooStyle" in v.message for v in violations)


# ---------------------------------------------------------------------------
# Rule 2 — direct BaseModel subclass must declare model_config
# ---------------------------------------------------------------------------


class TestRule2MissingModelConfig:
    def test_passes_with_model_config(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "good.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class MyStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
                x: int
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 2]
        assert not violations

    def test_fails_when_missing(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "bad.py",
            """\
            from pydantic import BaseModel

            class RootStyle(BaseModel):
                x: int
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 2]
        assert len(violations) == 1
        assert "RootStyle" in violations[0].message

    def test_enum_subclass_exempt(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "enum.py",
            """\
            from enum import Enum
            from pydantic import BaseModel

            class Color(str, Enum, BaseModel):
                red = "red"
            """,
        )
        # Enum bases suppress Rule 2
        violations = [v for v in check_file(f) if v.rule == 2]
        assert not violations

    def test_indirect_subclass_exempt(self, tmp_path: Path) -> None:
        """A subclass of a project-internal model is not flagged (no BaseModel in direct bases)."""
        f = _tmp_file(
            tmp_path,
            "indirect.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class BaseStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")

            class SubStyle(BaseStyle):
                y: str
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 2]
        assert not violations


# ---------------------------------------------------------------------------
# Rule 3 — Compiled prefix banned
# ---------------------------------------------------------------------------


class TestRule3CompiledPrefix:
    def test_passes_bare_name(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "good.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class Board(BaseModel):
                model_config = ConfigDict(extra="forbid")
                id: str
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 3]
        assert not violations

    def test_fails_compiled_prefix(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "bad.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class CompiledBoard(BaseModel):
                model_config = ConfigDict(extra="forbid")
                id: str
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 3]
        assert len(violations) == 1
        assert "CompiledBoard" in violations[0].message

    def test_fails_any_compiled_prefix(self, tmp_path: Path) -> None:
        f = _tmp_file(
            tmp_path,
            "two.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class CompiledChart(BaseModel):
                model_config = ConfigDict(extra="forbid")

            class CompiledStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 3]
        assert len(violations) == 2


# ---------------------------------------------------------------------------
# Rule 4 — _types suffix banned
# ---------------------------------------------------------------------------


class TestRule4TypesSuffix:
    def test_passes_normal_name(self, tmp_path: Path) -> None:
        f = _tmp_file(tmp_path, "compiled.py", "x = 1\n")
        violations = [v for v in check_file(f) if v.rule == 4]
        assert not violations

    def test_fails_types_suffix(self, tmp_path: Path) -> None:
        f = _tmp_file(tmp_path, "chart_types.py", "x = 1\n")
        violations = [v for v in check_file(f) if v.rule == 4]
        assert len(violations) == 1
        assert "_types" in violations[0].message

    def test_fails_compiled_types_suffix(self, tmp_path: Path) -> None:
        f = _tmp_file(tmp_path, "compiled_types.py", "x = 1\n")
        violations = [v for v in check_file(f) if v.rule == 4]
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# Rule 5 — T | None = None must have justification comment
# ---------------------------------------------------------------------------

# Rule 5 only fires for files under RULE5_FILES (absolute paths).
# We override the set during testing via a patch.


class TestRule5OptionalWithoutComment:
    def _make_rule5_file(self, tmp_path: Path, source: str) -> Path:
        """Write source to a path that matches _RULE5_TARGETS."""
        import check_models as cm

        f = tmp_path / "compiled.py"
        f.write_text(textwrap.dedent(source))
        # Patch _RULE5_TARGETS to include our temp file's parent directory.
        self._original_targets = cm._RULE5_TARGETS
        cm._RULE5_TARGETS = (*cm._RULE5_TARGETS, tmp_path)
        return f

    def teardown_method(self, _method: object) -> None:
        # Restore _RULE5_TARGETS in case a test patched it.
        import check_models as cm

        if hasattr(self, "_original_targets"):
            cm._RULE5_TARGETS = self._original_targets

    def test_passes_with_inline_comment(self, tmp_path: Path) -> None:
        f = self._make_rule5_file(
            tmp_path,
            """\
            from pydantic import BaseModel, ConfigDict

            class FooAxisStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
                angle: float | None = None  # None = VL chooses angle
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 5]
        assert not violations

    def test_passes_with_preceding_block_comment(self, tmp_path: Path) -> None:
        f = self._make_rule5_file(
            tmp_path,
            """\
            from pydantic import BaseModel, ConfigDict

            class FooAxisStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
                # Only set on axis_y; None on other variants skips the VL property.
                categorical_orient: str | None = None
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 5]
        assert not violations

    def test_fails_without_any_comment(self, tmp_path: Path) -> None:
        f = self._make_rule5_file(
            tmp_path,
            """\
            from pydantic import BaseModel, ConfigDict

            class FooScaleStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
                zero: bool | None = None
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 5]
        assert len(violations) == 1
        assert "zero" in violations[0].message

    def test_passes_non_none_default(self, tmp_path: Path) -> None:
        """T | None = False does not trigger Rule 5 (default is not None)."""
        f = self._make_rule5_file(
            tmp_path,
            """\
            from pydantic import BaseModel, ConfigDict

            class Cfg(BaseModel):
                model_config = ConfigDict(extra="forbid")
                hidden: bool | None = False
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 5]
        assert not violations

    def test_rule5_not_triggered_outside_compiled_files(self, tmp_path: Path) -> None:
        """Rule 5 is scoped to theme.py / normalized.py / config.py files only."""
        f = _tmp_file(
            tmp_path,
            "authored.py",
            """\
            from pydantic import BaseModel, ConfigDict

            class AuthoredStyle(BaseModel):
                model_config = ConfigDict(extra="forbid")
                angle: float | None = None
            """,
        )
        violations = [v for v in check_file(f) if v.rule == 5]
        assert not violations


# ---------------------------------------------------------------------------
# Integration: current tree is clean
# ---------------------------------------------------------------------------


class TestCurrentTreeClean:
    def test_models_tree_passes_all_rules(self) -> None:
        """The live compile/models/ tree must produce zero violations."""
        from check_models import MODELS_ROOT, check_file

        all_violations = []
        for path in sorted(MODELS_ROOT.rglob("*.py")):
            all_violations.extend(check_file(path))

        messages = "\n".join(str(v) for v in all_violations)
        assert not all_violations, (
            f"{len(all_violations)} model-convention violation(s) found:\n{messages}"
        )
