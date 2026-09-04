"""Live-Postgres integration coverage for the EXPLAIN warehouse-check tier.

The EXPLAIN tier's unit tests fake the adapter registry, so nothing there
proves a real engine accepts `EXPLAIN <authored sql>` through the real
dbt-postgres adapter, rejects a dropped column through it, or that a
connect-time fault stays "unchecked". This module boots a throwaway Postgres
cluster (initdb + pg_ctl on the runner's own binaries — GitHub's
ubuntu-latest ships them) and pins all three against the real engine.

Skips, never fails, when the environment cannot host a cluster: no Postgres
binaries on the machine, or running as root with no unprivileged `postgres`
user to hand the server to (Postgres refuses to run as root).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from dbt_charts.agent_api.validate import validate_paths
from dbt_charts.cli.filesystem_project import FilesystemProject
from dbt_charts.core.execute.adapters.adapter_registry import build_adapter_registry

_BOARD = """\
title: Orders
source: pg
queries:
  o: SELECT customer_id, amount FROM orders
charts:
  tbl:
    query: o
    type: table
rows:
  - tbl
"""


def _pg_bindir() -> str | None:
    on_path = shutil.which("initdb")
    if on_path:
        return str(Path(on_path).parent)
    candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin"))
    return str(candidates[-1]) if candidates else None


_BINDIR = _pg_bindir()
_AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0

pytestmark = [
    # Cluster boot (initdb + pg_ctl + readiness + adapter connect) exceeds the
    # repo-wide 30s per-item timeout, which covers fixture setup too — a
    # timeout landing during initdb/pg_ctl start, before the try, would leak
    # the postmaster. Registered in test_slow_family_timeouts.py.
    pytest.mark.timeout(180),
    # One worker owns the cluster: the fixture is module-scoped, and the
    # unreachable-server test must never race another worker's live cluster.
    pytest.mark.xdist_group("postgres_explain_cluster"),
]

_needs_pg = pytest.mark.skipif(
    _BINDIR is None, reason="no Postgres server binaries on this machine"
)


def test_postgres_binaries_present_on_ci() -> None:
    """The all-skipped silent pass this module must not become: if the runner
    image drops its Postgres binaries, CI fails loudly instead of reporting a
    green test-integration with the regression gate quietly gone. A laptop
    without Postgres still skips."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        pytest.skip("binary-presence canary is a CI-only guarantee")
    assert _BINDIR is not None, (
        "test-integration runs on a machine with no Postgres server binaries — "
        "the live-EXPLAIN gate would silently skip; install them or repoint "
        "_pg_bindir"
    )


def _run_as_server_user(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a server command, dropping to the `postgres` user when we are root.

    The root branch is exercised only in root dev containers — GitHub's hosted
    runners run unprivileged and never enter it. Every failure inside it routes
    to a skip, never a false pass.
    """
    if not _AS_ROOT:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    quoted = " ".join(f"'{c}'" for c in cmd)
    return subprocess.run(
        ["su", "postgres", "-c", quoted], cwd=cwd, capture_output=True, text=True
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pg_cluster(tmp_path_factory: pytest.TempPathFactory):
    """A running throwaway Postgres with wh.orders(customer_id, amount)."""
    assert _BINDIR is not None
    if _AS_ROOT:
        try:
            import pwd

            pwd.getpwnam("postgres")
        except KeyError:
            pytest.skip("running as root and no `postgres` user to run the server as")

    base = tmp_path_factory.mktemp("pg")
    if _AS_ROOT:
        shutil.chown(base, user="postgres")
        base.chmod(0o700)
        # tmp_path_factory parents are 0o700 root-owned; the server user needs
        # to traverse them to reach its datadir.
        for parent in [base.parent, base.parent.parent]:
            parent.chmod(0o711)
    port = _free_port()
    data = base / "data"

    init = _run_as_server_user(
        [
            f"{_BINDIR}/initdb",
            "-D",
            str(data),
            "-U",
            "dct",
            "--auth=trust",
            "-E",
            "UTF8",
        ],
        cwd=base,
    )
    if init.returncode != 0:
        pytest.skip(f"initdb failed on this machine: {init.stderr[-300:]}")
    start = _run_as_server_user(
        [
            f"{_BINDIR}/pg_ctl",
            "-D",
            str(data),
            "-o",
            f"-p {port} -k {base} -c listen_addresses=127.0.0.1",
            "-l",
            str(base / "pg.log"),
            "start",
        ],
        cwd=base,
    )
    if start.returncode != 0:
        # pg_ctl's wait can time out while leaving the postmaster running —
        # stop before skipping so the failure path never leaks the process.
        _run_as_server_user(
            [f"{_BINDIR}/pg_ctl", "-D", str(data), "-m", "immediate", "stop"], cwd=base
        )
        pytest.skip(f"pg_ctl start failed on this machine: {start.stderr[-300:]}")

    # From here the server is running: everything further — readiness wait,
    # seeding, the tests themselves — sits inside the try so a failure at any
    # point still stops the process instead of leaking it onto the machine.
    psql_base = [f"{_BINDIR}/psql", "-h", "127.0.0.1", "-p", str(port), "-U", "dct"]
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            ready = subprocess.run(
                [*psql_base, "-d", "postgres", "-c", "SELECT 1"],
                capture_output=True,
                text=True,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.3)
        else:
            pytest.skip("throwaway Postgres never became ready")

        subprocess.run(
            [*psql_base, "-d", "postgres", "-c", "CREATE DATABASE wh"], check=True
        )
        subprocess.run(
            [
                *psql_base,
                "-d",
                "wh",
                "-c",
                "CREATE TABLE orders (customer_id INTEGER, amount DOUBLE PRECISION);"
                "INSERT INTO orders VALUES (1, 10.0)",
            ],
            check=True,
        )
        yield {"port": port, "psql": psql_base}
    finally:
        _run_as_server_user(
            [f"{_BINDIR}/pg_ctl", "-D", str(data), "-m", "immediate", "stop"], cwd=base
        )


def _project(tmp_path: Path, port: int) -> Path:
    (tmp_path / "dbt_charts.yml").write_text(
        "sources:\n"
        "  pg:\n"
        "    type: postgres\n"
        "    host: 127.0.0.1\n"
        f"    port: {port}\n"
        "    dbname: wh\n"
        "    user: dct\n"
        '    password: ""\n'
    )
    (tmp_path / "charts").mkdir()
    (tmp_path / "charts" / "board.yaml").write_text(_BOARD)
    return tmp_path


def _validate(root: Path):
    project = FilesystemProject(root)
    registry = build_adapter_registry(project)
    results = validate_paths(
        [root / "charts" / "board.yaml"],
        project=project,
        adapter_registry=registry,
    )
    assert len(results) == 1
    return results[0]


@_needs_pg
def test_valid_query_passes_with_the_columns_only_warning(pg_cluster, tmp_path):
    root = _project(tmp_path, pg_cluster["port"])
    result = _validate(root)
    assert not result.errors, [e.model_dump() for e in result.errors]
    assert "WARN-COLUMN-CHECK-UNAVAILABLE" in {w.code for w in result.warnings}


@_needs_pg
def test_dropped_column_fails_through_a_real_explain(pg_cluster, tmp_path):
    """The drift case itself: rename the column in the warehouse only, and the
    board that still references it must fail — through a real Postgres EXPLAIN,
    not a faked registry."""
    root = _project(tmp_path, pg_cluster["port"])
    subprocess.run(
        [
            *pg_cluster["psql"],
            "-d",
            "wh",
            "-c",
            "ALTER TABLE orders RENAME COLUMN customer_id TO user_id",
        ],
        check=True,
    )
    try:
        result = _validate(root)
    finally:
        subprocess.run(
            [
                *pg_cluster["psql"],
                "-d",
                "wh",
                "-c",
                "ALTER TABLE orders RENAME COLUMN user_id TO customer_id",
            ],
            check=True,
        )
    errors = {e.code for e in result.errors}
    assert "ERR-WAREHOUSE-QUERY-INVALID" in errors, errors
    invalid = next(e for e in result.errors if e.code == "ERR-WAREHOUSE-QUERY-INVALID")
    assert "customer_id" in invalid.message


def test_unreachable_server_is_unchecked_not_invalid(tmp_path):
    """A connect-time fault says nothing about the SQL: never 'your query is
    broken', always the unverified warning."""
    # Hold the port bound without listening for the duration: connections are
    # deterministically refused, and no xdist sibling's cluster can claim it.
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        root = _project(tmp_path, blocker.getsockname()[1])
        result = _validate(root)
    assert not result.errors, [e.model_dump() for e in result.errors]
    assert "WARN-WAREHOUSE-CHECK-UNAVAILABLE" in {w.code for w in result.warnings}
