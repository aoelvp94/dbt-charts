"""The move_file tool against a real on-disk FilesystemProject.

Exercises the exact dispatch path the agent loop calls per tool call
(``dispatch_tool_call`` — the loop in ``dbt_charts.ai.agent.run_agent`` does
nothing else with a tool call). Drives dispatch directly against a real ``project_dir`` on disk rather than
through a faked client (as ``dbt-charts/tests/core/test_ai_agent.py`` does), so
the guarantee under test is the on-disk file move itself, not the loop that
reaches it.
"""

from __future__ import annotations

from pathlib import Path

from dbt_charts.agent_api import ProjectSession
from dbt_charts.ai.context import DbtChartsAIContext
from dbt_charts.ai.tools import dispatch_tool_call


def test_move_file_tool_call_renames_on_disk_and_rewrites_exact_link(
    project_dir: Path,
) -> None:
    boards = project_dir / "charts"
    boards.mkdir()
    (boards / "rev.yml").write_text("title: Revenue\n", encoding="utf-8")
    (boards / "exec.yml").write_text(
        "charts:\n  a:\n    type: kpi\n    link: rev\n", encoding="utf-8"
    )

    with ProjectSession.open(project_dir, read_only=False) as project_session:
        ctx = DbtChartsAIContext(project_session=project_session)
        result = dispatch_tool_call(
            "move_file",
            {"source_path": "charts/rev.yml", "destination_path": "charts/growth.yml"},
            context=ctx,
        )

    assert result["success"] is True, result.get("error")
    assert not (boards / "rev.yml").exists()
    assert (boards / "growth.yml").read_text(encoding="utf-8") == "title: Revenue\n"
    assert result["links_rewritten"] == 1
    assert (boards / "exec.yml").read_text(encoding="utf-8") == (
        "charts:\n  a:\n    type: kpi\n    link: growth\n"
    )
