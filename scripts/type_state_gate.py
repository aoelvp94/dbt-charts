#!/usr/bin/env python3
"""Type-state merge-base gate for ``dbt_charts/core``.

Compares ``dbt_charts/core`` at the PR's merge base against HEAD, live, on
every run. No committed baseline: nothing for two branches to conflict over,
and no slack to accumulate between runs.

Five categories are blocking: ``silent_fallback``, ``cast``, ``type_ignore``,
``object_annotation``, ``explicit_any``. ``optional`` is report-only: `T |
None` is a contract in this repo, not rot on its own. Both kinds of category
use the same rule — a head site counts iff it is unmarked **and** its line
span intersects a line added or modified since the merge base; a blocking
category fails the gate when any site counts, a report-only category only
prints them. Site identity is diff-scoped, not inferred from line text
(ambiguous by construction: 862 of 1515 real ``explicit_any`` sites in
``dbt_charts/core`` share stripped text with another site). Git already
solves identity, exactly, with rename detection, so a pure ``git mv`` carries
its sites for free and needs no new markers.

The accepted trade-off: editing a line that already carries pre-existing
unmarked rot flags it, because you touched it. The gate lists every counted
site with the source line and the marker to paste:

    # type-state: <category> — <reason>

Usage (from the dbt_charts project root, monorepo or standalone)::

    uv run python scripts/type_state_gate.py [--base REF]

``--base`` defaults to ``git merge-base origin/main HEAD``. HEAD is always
counted from the working tree (tracked files via ``git ls-files``, content
read from disk), so uncommitted edits to ``dbt_charts/core`` are caught too.
The changed-line set comes from two git-diff passes against the working tree
(not ``base...HEAD``), so uncommitted edits are covered there too.

Exit codes: 0 clean, 1 a blocking category has a counted site, 2 the gate
itself could not run (git/environment failure, moved subtree, malformed
marker, unparseable source) — distinct from 1 so CI and the pre-push hook can
tell "broken setup" from "added rot".
"""

from __future__ import annotations

import argparse
import os.path
import re
import subprocess
import sys
from pathlib import Path
from typing import TextIO

# type_state_counter.py lives in the same directory as this script in both the
# monorepo (dbt-charts/scripts/) and the standalone export (scripts/ after
# Copybara core.move("dbt-charts", "")).
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from type_state_counter import (  # noqa: E402
    CATEGORIES,
    FileCounts,
    Site,
    count_type_state,
    suggest_marker_line,
)

# Derived, not listed: a category added to CATEGORIES that isn't explicitly
# report-only defaults to blocking, not the other way around — a silent
# default to advisory would let a seventh rot category ship with no gate.
REPORT_ONLY = frozenset({"optional"})
BLOCKING = frozenset(CATEGORIES) - REPORT_ONLY

# `@@ -<old> +<new> @@`; only the new (head) side matters — that's where an
# added or modified line lands. Count is omitted (implies 1) when a hunk
# touches exactly one line.
_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"not inside a git repository: {result.stderr.strip()}")
    return Path(result.stdout.strip())


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def _resolve_base(repo_root: Path, base_arg: str | None) -> str:
    if base_arg:
        return _git(repo_root, "rev-parse", base_arg)
    result = subprocess.run(
        ["git", "merge-base", "origin/main", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not resolve a merge base against origin/main "
            f"({result.stderr.strip()}). Run `git fetch origin main` and retry."
        )
    return result.stdout.strip()


def _read_head_sources(repo_root: Path, subdir: str) -> dict[str, str]:
    """Read tracked .py files under *subdir*, with content from the working tree.

    Uses ``git ls-files`` (respects .gitignore, excludes untracked cruft)
    rather than a directory walk — a walk would also count untracked and
    gitignored .py files, which are exactly the files git does not track.
    Content still comes from disk, not a git blob, so uncommitted edits to
    already-tracked files are counted too — this catches rot before you even
    commit it, not only what a `git push` would send.
    """
    output = _git(repo_root, "ls-files", "-z", "--", subdir)
    sources: dict[str, str] = {}
    for rel in output.split("\0"):
        if not rel or not rel.endswith(".py"):
            continue
        path = repo_root / rel
        try:
            sources[rel] = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"{rel} is tracked by git but missing from the working tree "
                "(deleted without `git rm`?). Stage the deletion or restore the file."
            ) from exc
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"{rel} is not valid UTF-8: {exc}") from exc
    return sources


def _changed_paths(
    repo_root: Path, base_sha: str, subdir: str
) -> list[tuple[str, str | None]]:
    """List (new_path, old_path) pairs under *subdir* changed since base, via numstat.

    ``old_path`` is ``None`` except for a detected rename (``-M``), where the
    per-file diff below needs *both* paths in its pathspec — filtering a diff
    to only the new path can't correlate it with a same-named-differently
    base entry, so a rename+modify would otherwise show as the whole new file
    added, not the incremental change.

    The numstat diff itself is run **unscoped** (no ``-- subdir`` pathspec),
    then filtered to entries whose new path lands under *subdir* — a
    ``-M``-scoped diff can only pair a rename whose old and new paths both
    fall inside the given pathspec, so restricting to *subdir* up front would
    blind rename detection to any file whose *subdir* itself moved (e.g. the
    whole core package relocating to a new parent directory), showing every
    such file as 100% newly added instead of unchanged.

    ``-z`` gives a strict machine format: NUL-separated, and paths are never
    quoted regardless of ``core.quotePath`` (unlike the non-``-z`` form, which
    is the only one that flag would matter for). Normal entries are
    ``<ins>\\t<del>\\t<path>``; a rename is ``<ins>\\t<del>\\t`` (empty path
    field) followed by two more NUL-terminated fields, the old path then the
    new one. ``split("\\t", 2)`` caps the split at the path field — a path may
    legally contain a tab, and an unbounded split would silently truncate it.
    """
    result = subprocess.run(
        ["git", "diff", "--numstat", "-z", "-M", base_sha],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git diff --numstat failed: {result.stderr.strip()}")

    prefix = subdir if subdir.endswith("/") else subdir + "/"
    fields = result.stdout.split("\0")
    entries: list[tuple[str, str | None]] = []
    i = 0
    while i < len(fields):
        field = fields[i]
        if not field:
            i += 1
            continue
        parts = field.split("\t", 2)
        path = parts[2] if len(parts) > 2 else ""
        if path:
            if path.startswith(prefix):
                entries.append((path, None))
            i += 1
        else:
            # Rename: this field's path is empty; the next two NUL fields are
            # the old and new paths.
            if i + 2 >= len(fields):
                raise RuntimeError(
                    "git diff --numstat produced a truncated rename record "
                    f"({field!r}) — expected two more NUL-separated fields"
                )
            old_path, new_path = fields[i + 1], fields[i + 2]
            if new_path.startswith(prefix):
                entries.append((new_path, old_path))
            i += 3
    return entries


def _added_line_ranges(
    repo_root: Path, base_sha: str, subdir: str
) -> dict[str, list[tuple[int, int]]]:
    """Map path -> 1-indexed inclusive (start, end) line ranges added or modified since base.

    Diffs one changed file per invocation, against the working tree (not
    ``base...HEAD``) so uncommitted edits are covered the same way
    ``_read_head_sources`` already reads them. One file per invocation means
    there is no path to attribute inside the diff output and no file header
    to parse at all — only ``@@`` hunk lines, which is what closes the three
    ways a single multi-file invocation can be spoofed: an added line whose
    text happens to start with ``+++ `` hijacking a parsed "current file";
    ``diff.mnemonicPrefix`` / `color.diff=always` / ``diff.dstPrefix`` /
    ``diff.external`` changing or suppressing the header text a parser reads;
    and ``core.quotePath`` quoting a non-ASCII path so a prefix-strip no-ops.
    ``--no-ext-diff --no-color`` still pin the two of those that apply to a
    single-file invocation, since a hunk line itself could otherwise be
    colorized. ``--text`` forces a text diff even if ``.gitattributes`` marks
    ``*.py -diff`` — without it, git reports "Binary files … differ" with no
    ``@@`` lines at all, and the gate passes silently. ``--no-textconv``
    closes the sibling hole: ``--text`` only defeats binary-file suppression,
    it does not stop a configured ``diff=<driver>`` attribute plus a
    ``textconv`` from diffing the driver's *output* instead of the file — a
    driver whose output ignores its input entirely emits zero ``@@`` hunks
    for a real content change. ``-M`` matches the
    numstat pass so both agree on renames regardless of ``diff.renames``: a
    rename passes both its old and new path in the pathspec (``_changed_paths``
    already found the correlation), which correctly limits the diff to the
    incremental change; passing only the new path would show the whole file
    as newly added.

    A hunk with a zero new-side count (``@@ -N +M,0 @@``) is a pure deletion:
    nothing lands on the head side at that position, so it contributes no
    range. Without this guard, ``new_start=M, new_count=0`` would produce the
    inverted range ``(M, M-1)``, which the site-overlap test
    (``site.lineno <= end and site.end_lineno >= start``) can still satisfy
    against a multi-line site — turning a deletion elsewhere inside a
    pre-existing multi-line site into a spurious flag on that site.
    """
    ranges: dict[str, list[tuple[int, int]]] = {}
    for new_path, old_path in _changed_paths(repo_root, base_sha, subdir):
        if not new_path.endswith(".py"):
            continue  # only .py sites are ever flagged; skip non-Python changes (e.g. binary assets)
        pathspec = [old_path, new_path] if old_path is not None else [new_path]
        result = subprocess.run(
            [
                "git",
                "--no-pager",
                "diff",
                "-M",
                "--no-ext-diff",
                "--no-color",
                "--text",
                "--no-textconv",
                "--unified=0",
                base_sha,
                "--",
                *pathspec,
            ],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"git diff failed for {new_path}: {result.stderr.strip()}"
            )
        file_ranges: list[tuple[int, int]] = []
        for line in result.stdout.split("\n"):
            if not line.startswith("@@ "):
                continue
            match = _HUNK_RE.match(line)
            if match is None:
                continue
            new_start = int(match.group(1))
            new_count = int(match.group(2)) if match.group(2) is not None else 1
            if new_count == 0:
                continue  # pure deletion: nothing added at this position
            file_ranges.append((new_start, new_start + new_count - 1))
        if file_ranges:
            ranges[new_path] = file_ranges
    return ranges


def _per_file_counts(sources: dict[str, str]) -> dict[str, FileCounts]:
    per_file: dict[str, FileCounts] = {}
    for path, source in sources.items():
        try:
            per_file[path] = count_type_state(source)
        except (ValueError, SyntaxError) as exc:
            raise ValueError(f"{path}: {exc}") from exc
    return per_file


def _flagged_sites(
    category: str,
    head_per_file: dict[str, FileCounts],
    head_sources: dict[str, str],
    added_ranges: dict[str, list[tuple[int, int]]],
) -> list[tuple[str, Site, str, int | None]]:
    """Unmarked *category* sites whose span intersects a line changed since the merge base.

    Each entry carries the line ``suggest_marker_line`` verified actually
    resolves a new marker to that site — not always ``site.lineno`` itself,
    since a narrower same-category sibling can claim that line first (see
    ``_print_sites``).
    """
    flagged: list[tuple[str, Site, str, int | None]] = []
    for path in sorted(head_per_file):
        ranges = added_ranges.get(path, [])
        if not ranges:
            continue
        source = head_sources[path]
        lines = source.split("\n")
        for site in head_per_file[path].unmarked_sites[category]:
            if any(
                site.lineno <= end and site.end_lineno >= start for start, end in ranges
            ):
                marker_line = suggest_marker_line(source, category, site)
                flagged.append(
                    (path, site, lines[site.lineno - 1].strip(), marker_line)
                )
    return flagged


def _print_sites(
    category: str,
    flagged: list[tuple[str, Site, str, int | None]],
    *,
    out: TextIO,
) -> None:
    """Print one paste-ready marker suggestion per flagged site, grouped by (path, lineno).

    Two or more sites can share a `lineno` (the grouping key, which is each
    site's *first* line) without needing the same marker line — e.g. `d.get(k,
    1) or [...]` is a narrower call site and a wider BoolOp site, both
    starting on line 1 but resolving (via `suggest_marker_line`) to different
    lines. The explode-the-line instruction is only warranted when two sites'
    `marker_line` values actually collide: only one marker can attach per
    physical line (everything after the first `#` is a single COMMENT token),
    so N sites resolving to the same line describes a fix that cannot be
    applied. Distinct `marker_line` values mean N separate, followable
    markers exist, so each is printed on its own.

    A lone flagged site can still be unfollowable: `_approve_sites` matches
    narrowest-span-first, so a marker on the site's own first line can be
    stolen by a narrower same-category sibling whose span also reaches that
    line (a chained `.get()` ladder is the common shape). `marker_line` is
    the line `suggest_marker_line` verified actually resolves to *this*
    site — it can differ from the site's first line, or not exist at all.
    """
    grouped: dict[tuple[str, int], list[tuple[str, int | None]]] = {}
    for path, site, text, marker_line in flagged:
        grouped.setdefault((path, site.lineno), []).append((text, marker_line))
    for path, lineno in sorted(grouped):
        entries = grouped[(path, lineno)]
        print(f"  {path}:{lineno}: {entries[0][0]}", file=out)
        marker_lines = [marker_line for _, marker_line in entries]
        collides = len(entries) > 1 and len(set(marker_lines)) < len(entries)
        if collides:
            print(
                f"    {len(entries)} {category} sites on this line — only one marker "
                f"can attach per line; explode it across {len(entries)} statements to "
                "mark each one",
                file=out,
            )
            continue
        for _, marker_line in entries:
            if marker_line is None:
                print(
                    f"    every line in this site's span already belongs to a narrower "
                    f"{category} sibling — explode the statement so this site gets its "
                    "own line",
                    file=out,
                )
            else:
                if marker_line != lineno:
                    print(
                        f"    line {lineno} is already claimed by a narrower {category} "
                        f"sibling — put the marker on line {marker_line} instead:",
                        file=out,
                    )
                print(f"    # type-state: {category} — <reason>", file=out)


def _print_blocking_result(
    category: str,
    base_sha: str,
    head_per_file: dict[str, FileCounts],
    head_sources: dict[str, str],
    added_ranges: dict[str, list[tuple[int, int]]],
) -> bool:
    """Print one blocking category's verdict; return True if it passed."""
    head_n = sum(len(c.unmarked_sites[category]) for c in head_per_file.values())
    head_total = sum(c.totals[category] for c in head_per_file.values())
    flagged = _flagged_sites(category, head_per_file, head_sources, added_ranges)

    if not flagged:
        print(f"{category}: unmarked {head_n}, OK — {head_total} sites total")
        return True

    print(
        f"FAIL {category}: {len(flagged)} unmarked site(s) on a line touched since "
        f"merge-base {base_sha}. If that looks stale, `git fetch origin main` and retry.",
        file=sys.stderr,
    )
    print(
        "  (editing a line that already carried unmarked rot flags it too — that's "
        "the honest behavior of a diff-scoped gate: mark it or leave the line alone)",
        file=sys.stderr,
    )
    _print_sites(category, flagged, out=sys.stderr)
    return False


def _print_report_only_result(
    category: str,
    head_per_file: dict[str, FileCounts],
    head_sources: dict[str, str],
    added_ranges: dict[str, list[tuple[int, int]]],
) -> None:
    head_n = sum(len(c.unmarked_sites[category]) for c in head_per_file.values())
    head_total = sum(c.totals[category] for c in head_per_file.values())
    flagged = _flagged_sites(category, head_per_file, head_sources, added_ranges)

    if not flagged:
        print(
            f"{category}: unmarked {head_n}, OK — {head_total} sites total (report-only)"
        )
        return
    print(
        f"{category}: {len(flagged)} unmarked site(s) on a line touched since merge-base "
        "(report-only, never fails)"
    )
    _print_sites(category, flagged, out=sys.stdout)


def run(base_arg: str | None) -> int:
    repo_root = _repo_root()
    base_sha = _resolve_base(repo_root, base_arg)

    # In the monorepo the git root contains a dbt-charts/ subdirectory; in the
    # standalone export (Copybara core.move("dbt-charts", "")), src/ is at the root.
    core_subdir = (
        "dbt-charts/src/dbt_charts/core"
        if (repo_root / "dbt-charts").is_dir()
        else "src/dbt_charts/core"
    )

    head_sources = _read_head_sources(repo_root, core_subdir)
    if not head_sources:
        # os.path.relpath, not Path.relative_to: this script's own real
        # location is never under a synthetic/test repo_root, and relpath
        # (unlike relative_to) doesn't raise when the two paths share no
        # common ancestor -- it just walks up via "..".
        self_path = os.path.relpath(_SCRIPTS_DIR / "type_state_gate.py", repo_root)
        raise RuntimeError(
            f"No .py files found under {core_subdir!r} in the working tree. "
            f"Did the core subtree move? Update the detection in {self_path}."
        )
    head_per_file = _per_file_counts(head_sources)

    added_ranges = _added_line_ranges(repo_root, base_sha, core_subdir)

    print(f"dbt_charts/core: base {base_sha} vs working tree.")
    ok = True
    for category in CATEGORIES:
        if category in BLOCKING:
            if not _print_blocking_result(
                category, base_sha, head_per_file, head_sources, added_ranges
            ):
                ok = False
        else:
            _print_report_only_result(
                category, head_per_file, head_sources, added_ranges
            )

    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default=None,
        help="Base ref (default: git merge-base origin/main HEAD)",
    )
    args = parser.parse_args(argv)
    try:
        return run(args.base)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"type-state gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
