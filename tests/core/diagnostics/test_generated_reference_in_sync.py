"""Drift guard: the wheel's error/warning reference copies must match render_reference(level).

Four copies must stay in sync, two per level:
  - agent_api/docs/{error,warning}-reference.md inside the package — wheel (no frontmatter)
  - apps/docs/docs/reference/{errors,warnings}.md — MkDocs site (has frontmatter); kept in
    sync by a guard test outside dbt-charts/, not covered here.

Mirrors test_generated_yaml_reference_in_sync.py. Fails when a REGISTRY code
changes without re-running `just gen-error-reference` / `just gen-warning-reference`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import markdown
import pytest

from ..._paths import DBT_CHARTS_DIR, DBT_CHARTS_PKG_DIR

_RECIPES = {"error": "gen-error-reference", "warning": "gen-warning-reference"}


def _generated_reference_content(level: str, *, with_anchors: bool = True) -> str:
    """Render the reference in a fresh interpreter to avoid test-order contamination."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from dbt_charts.core.diagnostics.render_reference import render_reference; "
                f"print(render_reference({level!r}, with_anchors={with_anchors!r}), end='')"
            ),
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
        cwd=DBT_CHARTS_DIR,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return result.stdout


@pytest.mark.parametrize(
    ("level", "path", "header", "with_anchors"),
    [
        (
            "error",
            DBT_CHARTS_PKG_DIR / "agent_api" / "docs" / "error-reference.md",
            "",
            False,
        ),
        (
            "warning",
            DBT_CHARTS_PKG_DIR / "agent_api" / "docs" / "warning-reference.md",
            "",
            False,
        ),
    ],
    ids=["errors-wheel", "warnings-wheel"],
)
def test_committed_reference_matches_generator(
    level: str, path: Path, header: str, with_anchors: bool
) -> None:
    """When this fails, run `just {gen-error,gen-warning}-reference` and commit the result."""
    content = _generated_reference_content(level, with_anchors=with_anchors)
    committed = path.read_text(encoding="utf-8")
    assert committed == header + content, (
        f"{path} is out of sync with dbt_charts.core.diagnostics.REGISTRY. "
        f"Run `just {_RECIPES[level]}` and commit the updated file."
    )


@pytest.mark.parametrize("level", ["error", "warning"])
def test_rendered_reference_survives_real_markdown(level: str) -> None:
    """Byte-equality drift tests only prove the committed file matches the
    generator's output — they can't catch a generator bug where both are
    wrong together (see render_reference.py's `_fence_for`: a bare single
    backtick around a message template broke on any template containing a
    backtick or a newline, and let `attr_list` read a trailing `{placeholder}`
    as an inline attribute list). This renders the generator's actual output
    through real Markdown with the site's `attr_list` extension and checks
    the HTML itself, not just the source text.
    """
    content = _generated_reference_content(level)
    html = markdown.markdown(
        content, extensions=["attr_list", "pymdownx.superfences", "toc"]
    )
    # A backtick inside a fenced <pre><code> block is the raw, correctly-fenced
    # payload (that's the whole point of _fence_for) — strip fenced blocks
    # before checking, so we only catch a backtick that broke *out* of its
    # fence and corrupted the surrounding prose into alternating code/text.
    prose_only = re.sub(r"<pre>.*?</pre>", "", html, flags=re.DOTALL)
    assert "`" not in prose_only, (
        f"A literal backtick survived into the rendered {level} reference "
        "prose (outside a <pre> block) — a message template's backticks "
        "broke out of its fence."
    )
    for code_tag in re.findall(r"<code[^>]*>", html):
        assert re.fullmatch(r"<code(?: class=\"[\w -]+\")?>", code_tag), (
            f"<code> tag carries an unexpected attribute in the rendered "
            f"{level} reference: {code_tag!r} — likely `attr_list` misreading "
            "a `{placeholder}` in a message template as an inline attribute list."
        )


@pytest.mark.parametrize(
    "path",
    [
        DBT_CHARTS_PKG_DIR / "agent_api" / "docs" / "error-reference.md",
        DBT_CHARTS_PKG_DIR / "agent_api" / "docs" / "warning-reference.md",
    ],
    ids=["errors-wheel", "warnings-wheel"],
)
def test_wheel_reference_has_no_inline_attribute_lists(path: Path) -> None:
    """The wheel copy is what `dct docs error-reference`/`warning-reference`
    print to a terminal and what the `dct://docs/*-reference` MCP
    resource serves verbatim. MkDocs' `{: #anchor }` inline-attribute-list
    syntax is needed on the docs-site copy (it's how `build_doc_url()`
    anchors resolve, since `toc: {permalink: true}` has no custom slugify)
    but is literal noise to a CLI reader or an agent — it must not leak
    into the wheel copy the way it does onto the docs-site page.
    """
    assert "{: #" not in path.read_text(encoding="utf-8"), (
        f"{path} leaks an MkDocs inline attribute list into the wheel copy — "
        f"run `just gen-{'error' if 'error' in path.name else 'warning'}-reference`."
    )
