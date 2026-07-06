"""Self-contained unit tests for MapNameSelect's DB-fed pagination math.

The bot has no test harness, conftest, or shared fixtures. This test constructs
MapNameSelect directly against a synthetic DB-fed list (no Discord runtime, no
live UI — the live discord.py UI is human-verify, Task 4). Run with:

    cd apps/bot && uv run pytest tests/test_map_name_select.py -x
"""

import math
import sys
from pathlib import Path

# The bot runs as `python main.py` from apps/bot, so `extensions` is a top-level
# import. pytest does not add the bot root to sys.path on its own (no conftest in
# this project), so bootstrap it here to stay self-contained.
_BOT_ROOT = str(Path(__file__).resolve().parent.parent)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from extensions.moderator import MapNameSelect, _PAGINATED_SELECT_PAGE_SIZE  # noqa: E402

# A synthetic DB-fed list, deliberately unsorted, of 63 names so the last page
# holds a remainder (63 = 25 + 25 + 13).
_RAW = [f"Map{i:02d}" for i in range(63)]
_SHUFFLED = _RAW[::-1]
_SORTED = sorted(_SHUFFLED)


def test_page_zero_yields_first_25_sorted() -> None:
    select = MapNameSelect(None, all_maps=_SHUFFLED, page=0)
    assert len(select.options) == _PAGINATED_SELECT_PAGE_SIZE
    labels = [o.label for o in select.options]
    assert labels == _SORTED[:_PAGINATED_SELECT_PAGE_SIZE]


def test_last_page_yields_remainder() -> None:
    total_pages = math.ceil(len(_SHUFFLED) / _PAGINATED_SELECT_PAGE_SIZE)
    last_page = total_pages - 1
    select = MapNameSelect(None, all_maps=_SHUFFLED, page=last_page)
    expected = _SORTED[last_page * _PAGINATED_SELECT_PAGE_SIZE :]
    assert len(select.options) == len(expected) == 13
    assert [o.label for o in select.options] == expected


def test_total_pages_is_ceil() -> None:
    select = MapNameSelect(None, all_maps=_SHUFFLED, page=0)
    assert select.total_pages == math.ceil(len(_SHUFFLED) / _PAGINATED_SELECT_PAGE_SIZE)
    assert select.total_pages == 3


def test_current_sets_default_on_matching_option() -> None:
    current = _SORTED[3]  # on page 0
    select = MapNameSelect(current, all_maps=_SHUFFLED, page=0)
    defaults = [o for o in select.options if o.default]
    assert len(defaults) == 1
    assert defaults[0].value == current

    # A current value not on the requested page sets no default there.
    off_page = _SORTED[30]  # on page 1
    select_pg0 = MapNameSelect(off_page, all_maps=_SHUFFLED, page=0)
    assert not any(o.default for o in select_pg0.options)


def test_empty_list_yields_no_options_no_crash() -> None:
    select = MapNameSelect(None, all_maps=[], page=0)
    assert len(select.options) == 0
    assert select.total_pages == 0
    assert select.page == 0


def test_page_stored_on_instance() -> None:
    select = MapNameSelect(None, all_maps=_SHUFFLED, page=1)
    assert select.page == 1
    labels = [o.label for o in select.options]
    assert labels == _SORTED[_PAGINATED_SELECT_PAGE_SIZE : 2 * _PAGINATED_SELECT_PAGE_SIZE]
