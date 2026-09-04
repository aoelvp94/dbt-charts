"""Guard: dbt-charts/ruff.toml keeps the Windows-portability rules on for non-core code."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from ._paths import DBT_CHARTS_DIR

pytestmark = pytest.mark.skipif(
    shutil.which("ruff") is None, reason="ruff CLI not on PATH"
)

_SNIPPET = (
    "import os\n"
    "def f() -> None:\n"
    "    with open('x') as fh:\n"  # PLW1514: no encoding=
    "        fh.read()\n"
    "    os.path.join('a', 'b')\n"  # PTH118: os.path.join → Path /
)


def _ruff_codes_for() -> set[str]:
    # Land the probe in a temp dir UNDER dbt-charts/ so the nested dbt-charts/ruff.toml
    # governs it (Ruff walks up to the nearest config) — without writing into real
    # source, where a crashed run would leave a file that `ruff check .` then lints.
    probe_dir = Path(tempfile.mkdtemp(dir=DBT_CHARTS_DIR, prefix=".ruff_probe_"))
    probe = probe_dir / "probe.py"
    probe.write_text(_SNIPPET, encoding="utf-8")
    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format", "json", str(probe)],
            cwd=DBT_CHARTS_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    finally:
        shutil.rmtree(probe_dir, ignore_errors=True)
    return {item["code"] for item in json.loads(result.stdout or "[]")}


# Fails today because: dbt-charts/ruff.toml has no `extend-select`, so PLW1514
# and the PTH family are inactive — the probe snippet lints clean.
def test_dbt_charts_ruff_flags_missing_encoding_and_os_path() -> None:
    codes = _ruff_codes_for()
    assert "PLW1514" in codes, f"expected PLW1514 in {codes}"
    assert any(c.startswith("PTH") for c in codes), f"expected a PTH code in {codes}"
