import ast
from pathlib import Path

import dbt_charts.ai.mcp.server as mcp_server_module

_CACHE_OPENERS = {"open_cache", "project_cache_ctx"}


def test_mcp_server_opens_no_cache_of_its_own() -> None:
    """The MCP surface receives its project and cache; it opens neither.

    ``dct mcp serve`` is the composition root: it builds the FilesystemProject,
    opens the cache, and injects both into ``run_server``. A cache-opening
    import here — from core's cache backends or from
    the ``dbt_charts.agent_api.cache`` seam — means this surface took back a
    lifecycle its caller already owns.
    """
    source = Path(mcp_server_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        names = {alias.name for alias in node.names}
        if node.module == "dbt_charts.core.execute.duckdb_cache":
            offenders.append(node.module)
        if names & _CACHE_OPENERS:
            offenders.append(f"{node.module}: {sorted(names & _CACHE_OPENERS)}")

    assert not offenders, (
        "ai/mcp/server.py must not open a cache — the cache is injected by "
        f"`dct mcp serve`, its composition root. Found: {offenders}"
    )
