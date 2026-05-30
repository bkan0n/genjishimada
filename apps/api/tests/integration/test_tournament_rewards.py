"""Integration tests for the tournament rewards engine.

Wave-0 scaffold. The end-to-end reward grant / streak reset flows (08-03) fill
this in. The placeholder below keeps the module collectible so downstream plans'
`<verify>` commands have a target.
"""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.domain_tournaments]


def test_tournament_rewards_scaffold_collects() -> None:
    """Placeholder so the module collects; replaced in 08-03."""
    assert True
