"""Fenced-comment stripping for embedded JS/CSS.

CSS comments are authored as Jinja `{# ... #}` comments and stripped natively
by the Jinja engine at template-render time -- no custom code needed (see
test_svg_output_free_of_comments.py / test_goldens_free_of_comments.py for
that half).

JS comments can't use bare `{# ... #}`: the runtime scripts are also read raw
and executed directly (the JS behavioral test suite, Cloud's raw `<script>`
embed for chat), so they must stay valid, comment-and-all JavaScript at rest.
They're authored as `/*{# ... #}*/` -- a real JS block comment whose content
is the fence marker -- so raw consumers just see an ordinary comment, while
`strip_js_comments` finds the unambiguous `/*{#`...`#}*/` marker and removes
it. Unlike a general JS tokenizer, this needs no string/regex-literal
awareness: the four-character marker isn't something real code would ever
contain by coincidence, so a single non-greedy regex is enough.
"""

from __future__ import annotations

from dbt_charts.core.render.comment_stripping import strip_js_comments


def test_strips_a_single_fenced_comment() -> None:
    source = "var x = 1; /*{# trailing comment #}*/"
    stripped = strip_js_comments(source)
    assert "{#" not in stripped and "#}" not in stripped
    assert "var x = 1;" in stripped


def test_strips_a_multiline_fenced_comment() -> None:
    source = "/*{# line one\n   line two #}*/\nvar x = 1;"
    stripped = strip_js_comments(source)
    assert "{#" not in stripped and "#}" not in stripped
    assert "var x = 1;" in stripped


def test_strips_multiple_fenced_comments() -> None:
    source = "/*{# a #}*/\nvar x = 1; /*{# b #}*/\nvar y = 2; /*{# c #}*/"
    stripped = strip_js_comments(source)
    assert "{#" not in stripped
    assert "var x = 1;" in stripped
    assert "var y = 2;" in stripped


def test_preserves_url_inside_string_untouched() -> None:
    # Real code containing "//" or "/*" without the fence marker is left
    # completely alone -- this isn't a general comment stripper.
    source = "var url = 'http://www.w3.org/2000/svg'; /*{# a real comment #}*/"
    stripped = strip_js_comments(source)
    assert "http://www.w3.org/2000/svg" in stripped
    assert "a real comment" not in stripped


def test_preserves_plain_unfenced_comments() -> None:
    # Only the fenced form is recognized as strippable -- an ordinary // or
    # /* */ comment (not wrapped in the fence) ships through untouched.
    source = "// a plain comment\nvar x = 1; /* also plain */"
    stripped = strip_js_comments(source)
    assert "a plain comment" in stripped
    assert "also plain" in stripped


def test_stripped_comment_leaves_a_space_not_a_token_merge() -> None:
    # A fenced comment is replaced with a single space, never deleted
    # outright -- deleting it entirely would let the tokens on either side
    # fuse into one (`return` + `5` -> `return5`).
    source = "return/*{# explanatory note #}*/5;"
    stripped = strip_js_comments(source)
    assert "{#" not in stripped
    assert "return5" not in stripped
    assert stripped.strip() == "return 5;"


def test_preserves_regex_literal_containing_fence_like_chars() -> None:
    # A regex literal is real code, not a comment -- must survive untouched
    # even though it isn't wrapped in the fence.
    source = "var re = /https:\\/\\//g; /*{# a real comment #}*/"
    stripped = strip_js_comments(source)
    assert "/https:\\/\\//g" in stripped
    assert "a real comment" not in stripped
