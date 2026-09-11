"""Install the dbt charts VS Code / Cursor extension.

The extension is published to the VS Code Marketplace and to Open VSX under
the same ID (``dbtLabsInc.dbtcharts``), so one ``--install-extension``
argument resolves on both registries: ``code --install-extension
dbtLabsInc.dbtcharts`` for VS Code, ``cursor --install-extension
dbtLabsInc.dbtcharts`` for Cursor. The editor fetches, installs, and
thereafter updates the extension itself.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

EXTENSION_ID = "dbtLabsInc.dbtcharts"

# Editor name → CLI binary on PATH.
EDITORS: dict[str, str] = {
    "code": "code",
    "vscode": "code",  # alias
    "cursor": "cursor",
}


def install_extension(editor: str, emit: Callable[[str], None] = print) -> int:
    """Install the dbt charts extension into the named editor by marketplace ID.

    Returns shell-style exit code: 0 on success, non-zero on failure.
    ``editor`` is one of ``EDITORS`` keys (``code``, ``vscode``, ``cursor``).
    """
    cli = EDITORS.get(editor.lower())
    if cli is None:
        emit(f"Unknown editor '{editor}'. Supported: {', '.join(sorted(EDITORS))}.")
        return 2

    binary = shutil.which(cli)
    if binary is None:
        emit(
            f"'{cli}' not found on PATH — install the editor first, or open\n"
            f"{cli} once and enable its shell command from the command palette."
        )
        return 1

    emit(f"Installing dbt charts extension from the marketplace into {cli}…")
    try:
        result = subprocess.run(
            [binary, "--install-extension", EXTENSION_ID],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        emit(f"  {cli} --install-extension timed out after 60s.")
        return 1
    for line in (result.stdout or "").rstrip().splitlines():
        emit(f"  {line}")
    if result.returncode != 0:
        for line in (result.stderr or "").rstrip().splitlines():
            emit(f"  {line}")
        return result.returncode
    emit(f"✓ Installed dbt charts extension into {cli}.")
    return 0
