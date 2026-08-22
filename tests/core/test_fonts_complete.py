"""Every font file under `core/render/fonts/` must be claimed by the registry.

Wheel completeness for the same files is pinned by EXPECTED_ASSETS in
`test_wheel_asset_inventory.py`. This test owns the parallel-list problem that one
cannot: the Python side. Adding a font means dropping the file in the directory and
adding a `VendoredFace` row — this test fails until both halves exist.

An unclaimed font file is not merely untidy. Two files claiming one family is exactly
what broke Source Serif 4: a static build and a variable build both sat in the
directory handed to vl-convert, and which one it bound to was undefined.
"""

from __future__ import annotations

import threading
import time
from contextlib import ExitStack
from pathlib import Path

from dbt_charts.core import fonts as fonts_mod
from dbt_charts.core.fonts import FONT_REGISTRY

FONTS_DIR = fonts_mod.get_fonts_dir()


def _registered_filenames() -> set[str]:
    """Every filename the registry names, on either the measured or painted side."""
    names = {board.measure_file for board in FONT_REGISTRY}
    names.update(
        board.web_file for board in FONT_REGISTRY if board.web_file is not None
    )
    return names


def test_every_shipped_font_is_in_the_registry() -> None:
    registered = _registered_filenames()
    missing = sorted(
        p.name
        for p in FONTS_DIR.iterdir()
        if p.suffix in {".ttf", ".woff2"} and p.name not in registered
    )
    assert not missing, (
        f"Font files absent from FONT_REGISTRY: {missing}. Add a VendoredFace row for "
        "each, or delete the file — an unregistered font is either dead weight in the "
        "wheel or a second file competing for a family name."
    )


def test_get_fonts_dir_resolves_once_to_a_persistent_real_directory() -> None:
    """get_fonts_dir() must resolve the package resource exactly once and
    cache the persistent real directory — not rebuild a fresh Path every
    call. Repeated calls must return the identical object."""
    first = fonts_mod.get_fonts_dir()
    second = fonts_mod.get_fonts_dir()

    assert first is second
    assert first.is_dir()
    assert (first / "InterVariable.ttf").is_file()


def test_get_fonts_dir_is_thread_safe_against_concurrent_first_calls(
    monkeypatch,
) -> None:
    """Two threads racing on the very first call must not both enter the
    resource context. Without a lock this is a check-then-act race: both
    threads observe `_fonts_dir is None` before either finishes resolving it."""
    fresh_stack = ExitStack()
    monkeypatch.setattr(fonts_mod, "_fonts_dir", None)
    monkeypatch.setattr(fonts_mod, "_fonts_stack", fresh_stack)

    real_enter_context = fresh_stack.enter_context
    call_count = 0

    def slow_enter_context(cm):
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)  # widen the race window so both threads overlap
        return real_enter_context(cm)

    monkeypatch.setattr(fresh_stack, "enter_context", slow_enter_context)

    results: list[Path | None] = [None, None]

    def call(index: int) -> None:
        results[index] = fonts_mod.get_fonts_dir()

    t1 = threading.Thread(target=call, args=(0,))
    t2 = threading.Thread(target=call, args=(1,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert call_count == 1, (
        "get_fonts_dir() entered the resource context more than once"
    )
    assert results[0] is results[1]
