"""The ``aliases:`` absolute-URL rule is enforced at the authored boundary.

Enforcing it only where the alias is *consumed* meant one host raised at startup
and any host resolving claims from its own index silently dropped the entry —
no error page, no log line, no failing validate, and a claim that never fires.
Validating on the authored model fails the offending board identically wherever
that board is compiled, and leaves every other board untouched.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dbt_charts.core.compile.models.board.authored import AuthoredBoard


def test_absolute_aliases_are_accepted() -> None:
    board = AuthoredBoard(title="Tickets", aliases=["/data/db/main/tickets/detail/"])
    assert board.aliases == ["/data/db/main/tickets/detail/"]


@pytest.mark.parametrize(
    "alias",
    [
        # The shape you get copying a path out of an address bar.
        "data/db/main/tickets/detail/",
        "old-reports/",
        "https://example.com/elsewhere/",
    ],
)
def test_a_non_absolute_alias_is_rejected(alias: str) -> None:
    with pytest.raises(ValidationError, match="not absolute"):
        AuthoredBoard(title="Tickets", aliases=[alias])


def test_the_rejection_names_the_offending_alias() -> None:
    """The author has to be able to tell which entry to fix."""
    with pytest.raises(ValidationError, match="typo-here"):
        AuthoredBoard(title="T", aliases=["/fine/", "typo-here/"])
