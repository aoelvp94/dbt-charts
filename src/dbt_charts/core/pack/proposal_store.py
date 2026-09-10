"""Load and dump pack proposal YAML artifacts.

Proposals are transient — written to ``target/dbt_charts/proposals/``
and never committed. This module owns the single load/dump pair.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TID251 — writes transient proposal YAML to target/

import yaml

from dbt_charts.core.pack.models import PackProposal


def load_proposal(path: Path) -> PackProposal:
    """Load and validate a proposal YAML file.

    Args:
        path: Path to the YAML proposal file.

    Returns:
        A fully-validated :class:`PackProposal`.

    Raises:
        FileNotFoundError: When *path* does not exist.
        yaml.YAMLError: When the file contains invalid YAML syntax.
        pydantic.ValidationError: When the YAML structure does not match
            the :class:`PackProposal` contract.
    """
    if not path.exists():
        raise FileNotFoundError(f"Proposal file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PackProposal.model_validate(raw)


def dump_proposal(proposal: PackProposal, path: Path) -> None:
    """Serialize a proposal to YAML and write it to *path*.

    Creates parent directories as needed. Writes block-style YAML
    (default ``yaml.safe_dump`` output — no flow-style objects).

    Args:
        proposal: The :class:`PackProposal` to serialize.
        path: Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # by_alias=True so the YAML file uses the user-facing field name "schema"
    # (not the Python attribute "schema_name"). mode="json" gives plain Python
    # types (str/list/dict) that yaml.safe_dump handles without custom representers.
    data = proposal.model_dump(mode="json", by_alias=True)
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
