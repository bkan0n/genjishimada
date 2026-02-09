from __future__ import annotations

import asyncio
import math
from abc import ABC, abstractmethod
from collections import OrderedDict
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Generic, Literal, Protocol, Sequence, TypeVar, cast

import discord
from discord import AllowedMentions, ButtonStyle, ui
from discord.app_commands import AppCommandError

from utilities.base import BaseView
from utilities.errors import UserFacingError
from utilities.formatter import FormattableProtocol

if TYPE_CHECKING:
    from utilities._types import GenjiItx

T = TypeVar("T", bound=FormattableProtocol)

MAX_CACHE_SIZE = 5


class PaginatableProtocol(FormattableProtocol, Protocol):
    """Protocol for objects that can be paginated with API pagination.

    Extends FormattableProtocol with the total_results attribute required
    for API-based pagination.
    """

    total_results: int | None


TP = TypeVar("TP", bound=PaginatableProtocol)


class _NextButton(ui.Button["BasePaginatorView"]):
    view: "BasePaginatorView"

    def __init__(self) -> None:
        """Initialize the Next button."""
        super().__init__(
            style=ButtonStyle.blurple,
            label="Next",
            # TODO: > Emoji
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Advance to the next page and update the view.

        Args:
            itx (GenjiItx): The interaction context.
        """
        try:
            await self.view.navigate_next()
            await itx.response.edit_message(view=self.view, allowed_mentions=AllowedMentions.none())
        except Exception:
            await itx.response.send_message(
                "Failed to load page. Please try again.",
                ephemeral=True,
            )


class _PreviousButton(ui.Button["BasePaginatorView"]):
    view: "BasePaginatorView"

    def __init__(self) -> None:
        """Initialize the Previous button."""
        super().__init__(
            style=ButtonStyle.blurple,
            label="Previous",
            # TODO: < Emoji
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Navigate to the previous page and update the view.

        Args:
            itx (GenjiItx): The interaction context.
        """
        try:
            await self.view.navigate_previous()
            await itx.response.edit_message(view=self.view, allowed_mentions=AllowedMentions.none())
        except Exception:
            await itx.response.send_message(
                "Failed to load page. Please try again.",
                ephemeral=True,
            )


class PageNumberModal(discord.ui.Modal):
    number = discord.ui.TextInput(label="Number")
    value = None

    def __init__(self, limit: int) -> None:
        """Initialize the modal for entering a page number.

        Args:
            limit (int): The maximum valid page number.
        """
        super().__init__(title="Choose a page...")
        self.limit = limit
        self.number.placeholder = f"Must be an integer in range 1 - {self.limit}"

    async def on_submit(self, itx: GenjiItx) -> None:
        """Handle modal submission and validate input.

        Args:
            itx (GenjiItx): The interaction context.

        Raises:
            TypeError: If the entered value is not a valid integer within the limit.
        """
        await itx.response.defer(ephemeral=True, thinking=True)

        try:
            self.value = int(self.number.value)
            if not 1 <= self.value <= self.limit:
                raise ValueError("Value out of range.")
        except ValueError:
            raise TypeError("Invalid integer.")

        if self.value:
            await itx.delete_original_response()


class _PageNumberButton(ui.Button["BasePaginatorView"]):
    view: "BasePaginatorView"

    def __init__(self, total_pages: int) -> None:
        """Initialize the page number button.

        Args:
            total_pages (int): Total number of pages in the paginator.
        """
        super().__init__(
            style=ButtonStyle.grey,
            label=f"1/{total_pages}",
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Open modal to jump to a specific page number.

        Args:
            itx (GenjiItx): The interaction context.
        """
        try:
            modal = PageNumberModal(self.view.get_total_pages())
            await itx.response.send_modal(modal)
            await modal.wait()
            number = int(modal.number.value)
            await self.view.navigate_to_page(number - 1)
            await itx.edit_original_response(view=self.view, allowed_mentions=AllowedMentions.none())
        except Exception:
            await itx.response.send_message(
                "Failed to load page. Please try again.",
                ephemeral=True,
            )


class BasePaginatorView(ABC, BaseView, Generic[T]):
    """Abstract base class for paginated views.

    Provides shared UI components (buttons, modals) and defines abstract methods
    for navigation and data access that must be implemented by subclasses.
    """

    def __init__(
        self,
        title: str,
        *,
        page_size: int = 5,
    ) -> None:
        """Initialize the base paginator.

        Args:
            title (str): Title to display at the top of the paginator.
            page_size (int, optional): Number of items per page. Defaults to 5.
        """
        self._page_size = page_size
        self._title = title
        self._current_page_index = 0

        self._previous_button: _PreviousButton = _PreviousButton()
        self._page_number_button: _PageNumberButton = _PageNumberButton(1)
        self._next_button: _NextButton = _NextButton()

        # Call discord.ui.LayoutView.__init__ directly to skip BaseView's rebuild_components()
        # We'll call rebuild_components() after subclasses initialize their data
        discord.ui.LayoutView.__init__(self, timeout=600)

        # Manually set up BaseView attributes
        assert self.timeout
        timeout_dt = discord.utils.format_dt(discord.utils.utcnow() + timedelta(seconds=self.timeout), "R")
        self._end_time_string = f"-# ⚠️ This message will expire and become inactive {timeout_dt}."
        self.original_interaction: GenjiItx | None = None
        # Note: rebuild_components() will be called by subclasses after data is initialized

    @property
    def current_page_index(self) -> int:
        """int: The index of the currently active page."""
        return self._current_page_index

    @property
    def item_index_offset(self) -> int:
        """int: The starting global index offset for the current page.

        This value represents how far into the overall dataset the
        current page begins. For example, with a page size of 5:

        - Page 0 → offset 0
        - Page 1 → offset 5
        - Page 2 → offset 10

        When enumerating items on the current page, add this offset
        to each local index to get the global index across all pages.
        """
        return self._current_page_index * self._page_size

    @abstractmethod
    def get_total_pages(self) -> int:
        """Get the total number of pages.

        Returns:
            int: Total number of pages.
        """
        ...

    @abstractmethod
    def get_current_page_data(self) -> list[T]:
        """Get the data for the current page.

        Returns:
            list[T]: The current page's data items.
        """
        ...

    @abstractmethod
    async def navigate_to_page(self, page_index: int) -> None:
        """Navigate to a specific page index.

        Args:
            page_index (int): The target page index (0-based).

        Raises:
            Exception: If navigation fails (e.g., API error).
        """
        ...

    @abstractmethod
    async def navigate_next(self) -> None:
        """Navigate to the next page.

        Raises:
            Exception: If navigation fails (e.g., API error).
        """
        ...

    @abstractmethod
    async def navigate_previous(self) -> None:
        """Navigate to the previous page.

        Raises:
            Exception: If navigation fails (e.g., API error).
        """
        ...

    def build_page_body(self) -> Sequence[ui.Item]:
        """Build the display section for the current page.

        Returns:
            Sequence[ui.Item]: The UI items for the page.

        Raises:
            NotImplementedError: Must be implemented by subclasses.
        """
        raise NotImplementedError

    def build_additional_action_row(self) -> ui.ActionRow | None:
        """Build an additional action row under the pagination buttons."""
        return None

    def rebuild_components(self) -> None:
        """Rebuild all components for the current page."""
        self.clear_items()
        body = self.build_page_body()

        total_pages = self.get_total_pages()
        action_row = ()
        if total_pages > 1:
            self._page_number_button.label = f"{self._current_page_index + 1}/{total_pages}"
            action_row = (
                ui.ActionRow(
                    self._previous_button,
                    self._page_number_button,
                    self._next_button,
                ),
            )

        additional_action_row = ()
        if row := self.build_additional_action_row():
            additional_action_row = (
                ui.Separator(),
                row,
            )

        container = ui.Container(
            ui.TextDisplay(f"# {self._title}"),
            ui.Separator(),
            *body,
            ui.TextDisplay(f"# {self._end_time_string}"),
            *action_row,
            *additional_action_row,
        )
        self.add_item(container)

    async def on_error(self, itx: GenjiItx, error: Exception, item: ui.Item[Any], /) -> None:
        """Handle errors."""
        await itx.client.tree.on_error(itx, cast("AppCommandError", error))


class StaticPaginatorView(BasePaginatorView[T]):
    """In-memory paginator that loads all data at initialization.

    Suitable for small datasets or when all data is already available.
    """

    def __init__(
        self,
        title: str,
        data: Sequence[T],
        *,
        page_size: int = 5,
    ) -> None:
        """Initialize a paginated view with in-memory data.

        Args:
            title (str): Title to display at the top of the paginator.
            data (Sequence[T]): The data to paginate.
            page_size (int, optional): Number of items per page. Defaults to 5.
        """
        super().__init__(title, page_size=page_size)
        self.rebuild_data(data)
        # Now that _pages is initialized, rebuild components
        self.rebuild_components()

    @property
    def pages(self) -> list[list[T]]:
        """list[list[T]]: Chunked pages built from input data."""
        return self._pages

    @property
    def current_page(self) -> list[T]:
        """list[T]: The current page's content."""
        return self._pages[self._current_page_index]

    def get_total_pages(self) -> int:
        """Get the total number of pages.

        Returns:
            int: Total number of pages.
        """
        return len(self._pages)

    def get_current_page_data(self) -> list[T]:
        """Get the data for the current page.

        Returns:
            list[T]: The current page's data items.
        """
        return self.current_page

    def _get_requested_index(self, value: Literal[-1, 1]) -> int:
        """Calculate the new page index by increment or decrement with wraparound.

        Args:
            value (Literal[-1, 1]): Direction to move.

        Returns:
            int: New page index.
        """
        length = len(self._pages)
        return (self._current_page_index + value) % length

    async def navigate_to_page(self, page_index: int) -> None:
        """Navigate to a specific page index.

        Args:
            page_index (int): The target page index (0-based).
        """
        self._current_page_index = page_index % len(self._pages)
        self.rebuild_components()

    async def navigate_next(self) -> None:
        """Navigate to the next page."""
        self._current_page_index = self._get_requested_index(1)
        self.rebuild_components()

    async def navigate_previous(self) -> None:
        """Navigate to the previous page."""
        self._current_page_index = self._get_requested_index(-1)
        self.rebuild_components()

    def increment_page_index(self) -> None:
        """Increment the current page index and refresh the view.

        Deprecated: Use navigate_next() instead.
        """
        self._current_page_index = self._get_requested_index(1)
        self._page_number_button.label = f"{self._current_page_index + 1}/{len(self._pages)}"
        self.rebuild_components()

    def decrement_page_index(self) -> None:
        """Decrement the current page index and refresh the view.

        Deprecated: Use navigate_previous() instead.
        """
        self._current_page_index = self._get_requested_index(-1)
        self._page_number_button.label = f"{self._current_page_index + 1}/{len(self._pages)}"
        self.rebuild_components()

    def skip_to_page_index(self, value: int) -> None:
        """Jump directly to a specific page index.

        Deprecated: Use navigate_to_page() instead.

        Args:
            value (int): The target page index (0-based).
        """
        self._current_page_index = value % len(self._pages)
        self._page_number_button.label = f"{self._current_page_index + 1}/{len(self._pages)}"
        self.rebuild_components()

    def rebuild_data(self, data: Sequence[T]) -> None:
        """Rebuild paginated data and reset pagination state.

        Args:
            data (Sequence[T]): Data to paginate.
        """
        self._pages = list(discord.utils.as_chunks(data, self._page_size))
        self._current_page_index = 0

        self._previous_button = _PreviousButton()
        self._page_number_button = _PageNumberButton(len(self.pages))
        self._next_button = _NextButton()


class ApiPaginatorView(BasePaginatorView[TP]):
    """API-based paginator with hybrid caching and background prefetching.

    Fetches pages on-demand from an API and caches recently viewed pages.
    Suitable for large datasets where loading all data upfront is inefficient.
    """

    def __init__(
        self,
        title: str,
        fetch_func: Callable[..., Awaitable[list[TP]]],
        *,
        page_size: int = 5,
        initial_page: int = 1,
        empty_message: str = "No results found.",
    ) -> None:
        """Initialize an API-based paginator.

        Args:
            title (str): Title to display at the top of the paginator.
            fetch_func (Callable): Partial-bound API method that accepts page_number and page_size.
            page_size (int, optional): Number of items per page. Defaults to 5.
            initial_page (int, optional): Initial page number (1-based). Defaults to 1.
            empty_message (str, optional): Message to show when no results found.
        """
        self._fetch_func = fetch_func
        self._empty_message = empty_message
        self._current_page: list[TP] = []
        self._page_cache: OrderedDict[int, list[TP]] = OrderedDict()
        self._total_results: int | None = None
        self._prefetch_task: asyncio.Task | None = None

        super().__init__(title, page_size=page_size)

        self._previous_button = _PreviousButton()
        self._page_number_button = _PageNumberButton(1)
        self._next_button = _NextButton()

    async def initialize(self) -> None:
        """Fetch initial page, extract total_results, validate non-empty.

        Must be called before sending the view to the user.

        Raises:
            UserFacingError: If initial fetch returns no results.
        """
        self._current_page = await self._fetch_func(page_number=1, page_size=self._page_size)

        if not self._current_page:
            raise UserFacingError(self._empty_message)

        first_item = self._current_page[0]
        if hasattr(first_item, "total_results") and first_item.total_results is not None:
            self._total_results = first_item.total_results
        else:
            self._total_results = len(self._current_page)

        self._add_to_cache(0, self._current_page)
        self.rebuild_components()
        self._start_prefetch()

    def get_total_pages(self) -> int:
        """Get the total number of pages.

        Returns:
            int: Total number of pages.
        """
        if self._total_results is None:
            return 1
        return math.ceil(self._total_results / self._page_size)

    def get_current_page_data(self) -> list[TP]:
        """Get the data for the current page.

        Returns:
            list[TP]: The current page's data items.
        """
        return self._current_page

    async def navigate_to_page(self, page_index: int) -> None:
        """Navigate to a specific page index.

        Args:
            page_index (int): The target page index (0-based).

        Raises:
            Exception: If API fetch fails.
        """
        total_pages = self.get_total_pages()
        page_index = page_index % total_pages

        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()

        if page_index in self._page_cache:
            self._current_page = self._page_cache[page_index]
            self._page_cache.move_to_end(page_index)
        else:
            self._current_page = await self._fetch_func(
                page_number=page_index + 1,
                page_size=self._page_size,
            )
            self._add_to_cache(page_index, self._current_page)

            if self._current_page:
                first_item = self._current_page[0]
                if hasattr(first_item, "total_results") and first_item.total_results is not None:
                    self._total_results = first_item.total_results

        self._current_page_index = page_index
        self.rebuild_components()
        self._start_prefetch()

    async def navigate_next(self) -> None:
        """Navigate to the next page.

        Raises:
            Exception: If API fetch fails.
        """
        next_index = (self._current_page_index + 1) % self.get_total_pages()
        await self.navigate_to_page(next_index)

    async def navigate_previous(self) -> None:
        """Navigate to the previous page.

        Raises:
            Exception: If API fetch fails.
        """
        prev_index = (self._current_page_index - 1) % self.get_total_pages()
        await self.navigate_to_page(prev_index)

    def _add_to_cache(self, page_index: int, data: list[TP]) -> None:
        """Add a page to the cache with LRU eviction.

        Args:
            page_index (int): The page index to cache.
            data (list[TP]): The page data.
        """
        self._page_cache[page_index] = data
        if len(self._page_cache) > MAX_CACHE_SIZE:
            oldest_key = next(iter(self._page_cache))
            del self._page_cache[oldest_key]

    def _start_prefetch(self) -> None:
        """Start background prefetch for adjacent pages."""
        if self._prefetch_task and not self._prefetch_task.done():
            self._prefetch_task.cancel()

        self._prefetch_task = asyncio.create_task(self._prefetch_adjacent_pages())

    async def _prefetch_adjacent_pages(self) -> None:
        """Background task to prefetch adjacent pages."""
        try:
            total_pages = self.get_total_pages()
            current = self._current_page_index

            prev_index = (current - 1) % total_pages
            next_index = (current + 1) % total_pages

            for page_index in [prev_index, next_index]:
                if page_index not in self._page_cache:
                    try:
                        data = await self._fetch_func(
                            page_number=page_index + 1,
                            page_size=self._page_size,
                        )
                        self._add_to_cache(page_index, data)
                    except Exception:
                        pass

        except asyncio.CancelledError:
            pass
        except Exception:
            pass


PaginatorView = StaticPaginatorView
