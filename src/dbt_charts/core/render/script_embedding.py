"""Helpers for embedding JavaScript into rendered SVG output."""

from dbt_charts.core.render.comment_stripping import strip_js_comments


def escape_cdata(content: str) -> str:
    """Escape sequences that would terminate a CDATA section."""
    return content.replace("]]>", "]]]]><![CDATA[>")


def embed_svg_script(script: str) -> str:
    """Wrap JavaScript for safe inline SVG execution.

    Strips `/*{# ... #}*/`-fenced comments before embedding -- engineering
    notes in the source scripts have no audience once shipped inline in an
    SVG.
    """
    script = strip_js_comments(script)
    script = escape_cdata(script)
    return f"""<script type="text/javascript">
<![CDATA[
{script}
]]>
</script>"""
