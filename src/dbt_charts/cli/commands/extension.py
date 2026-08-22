"""Install the dbt charts VS Code / Cursor extension.

The extension is mirrored to a public GCS bucket on every release.
``dct init code`` and ``dct init cursor``:

1. Download ``dataface-latest.vsix`` from
   ``https://storage.googleapis.com/dataface-downloads/`` (world-readable —
   no auth, no ``gh`` CLI).
2. Run ``code --install-extension <path>`` or
   ``cursor --install-extension <path>``.

Once the extension is on the Marketplace, the implementation will switch to
``code --install-extension dbt-charts.dbt-charts`` (a one-line change).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

DOWNLOADS_BASE = "https://storage.googleapis.com/dataface-downloads"
LATEST_VSIX = "dataface-latest.vsix"
LATEST_VSIX_URL = f"{DOWNLOADS_BASE}/{LATEST_VSIX}"

# Editor name → CLI binary on PATH.
EDITORS: dict[str, str] = {
    "code": "code",
    "vscode": "code",  # alias
    "cursor": "cursor",
}


def install_extension(editor: str, emit: Callable[[str], None] = print) -> int:
    """Auto-install the latest VSIX into the named editor.

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

    with tempfile.TemporaryDirectory(prefix="dft-ext-") as tmpdir:
        vsix_path = Path(tmpdir) / LATEST_VSIX
        emit(f"Downloading {LATEST_VSIX} from {DOWNLOADS_BASE}…")
        try:
            with urllib.request.urlopen(LATEST_VSIX_URL, timeout=60) as resp:
                vsix_path.write_bytes(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            emit(f"  download failed: {err}")
            return 1

        emit(f"Installing into {cli}…")
        try:
            result = subprocess.run(
                [binary, "--install-extension", str(vsix_path)],
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
