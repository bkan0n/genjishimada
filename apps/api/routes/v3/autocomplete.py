"""V4 Change Requests routes."""

from __future__ import annotations

from genjishimada_sdk.maps import Mechanics, OverwatchCode, OverwatchMap, PlaytestStatus, Restrictions, Tags
from litestar import Controller, MediaType, get
from litestar.di import Provide

from repository.autocomplete_repository import AutocompleteRepository, provide_autocomplete_repository


class AutocompleteController(Controller):
    """Endpoints for map change requests."""

    tags = ["Change Requests"]
    path = "/utilities"
    dependencies = {
        "autocomplete": Provide(provide_autocomplete_repository),
    }

    @get(
        path="/autocomplete/names",
        tags=["Autocomplete"],
        summary="Autocomplete Map Names",
        description="Return a list of map names ordered by text similarity to the provided search string.",
    )
    async def get_similar_map_names(
        self, autocomplete: AutocompleteRepository, search: str, limit: int = 5
    ) -> list[OverwatchMap] | None:
        """Get similar map names.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): The input string to compare.
            limit (int, optional): Maximum number of results. Defaults to 5.

        Returns:
            list[OverwatchMap] | None: A list of matching map names or `None` if no matches found.

        """
        return await autocomplete.get_similar_map_names(search, limit)

    @get(
        path="/transformers/names",
        tags=["Transformer"],
        media_type=MediaType.JSON,
        summary="Transform Map Name",
        description="Transform a free-form input string into the closest matching OverwatchMap name.",
    )
    async def transform_map_names(self, autocomplete: AutocompleteRepository, search: str) -> OverwatchMap | None:
        """Transform a map name into an OverwatchMap.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to transform.

        Returns:
            OverwatchMap | None: The closest matching map name, or `None` if no matches found.

        """
        return await autocomplete.transform_map_names(search)

    @get(
        path="/autocomplete/restrictions",
        tags=["Autocomplete"],
        summary="Autocomplete Map Restrictions",
        description="Return a list of map restrictions ordered by text similarity to the provided search string.",
    )
    async def get_similar_map_restrictions(
        self,
        autocomplete: AutocompleteRepository,
        search: str,
        limit: int = 5,
    ) -> list[Restrictions] | None:
        """Get similar map restrictions.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to compare.
            limit (int, optional): Maximum number of results. Defaults to 5.

        Returns:
            list[Restrictions] | None: Matching restriction names, or `None` if none found.

        """
        return await autocomplete.get_similar_map_restrictions(search, limit)

    @get(
        path="/transformers/restrictions",
        tags=["Transformer"],
        media_type=MediaType.JSON,
        summary="Transform Map Restriction",
        description="Transform a free-form input string into the closest matching map restriction.",
    )
    async def transform_map_restrictions(
        self, autocomplete: AutocompleteRepository, search: str
    ) -> OverwatchMap | None:
        """Transform a map name into a Restriction.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to transform.

        Returns:
            Restrictions | None: The closest matching restriction, or `None` if none found.

        """
        return await autocomplete.transform_map_restrictions(search)

    @get(
        path="/autocomplete/mechanics",
        tags=["Autocomplete"],
        summary="Autocomplete Map Mechanics",
        description="Return a list of mechanics ordered by similarity to the provided search string.",
    )
    async def get_similar_map_mechanics(
        self, autocomplete: AutocompleteRepository, search: str, limit: int = 5
    ) -> list[Mechanics] | None:
        """Get similar map mechanics.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to compare.
            limit (int, optional): Maximum number of results. Defaults to 5.

        Returns:
            list[Mechanics] | None: Matching mechanics, or `None` if none found.

        """
        return await autocomplete.get_similar_map_mechanics(search, limit)

    @get(
        path="/transformers/mechanics",
        tags=["Transformer"],
        media_type=MediaType.JSON,
        summary="Transform Map Mechanic",
        description="Transform a free-form input string into the closest matching map mechanic.",
    )
    async def transform_map_mechanics(self, autocomplete: AutocompleteRepository, search: str) -> Mechanics | None:
        """Transform a map name into a Mechanic.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to transform.

        Returns:
            Mechanics | None: The closest matching mechanic, or `None` if none found.

        """
        return await autocomplete.transform_map_mechanics(search)

    @get(
        path="/autocomplete/codes",
        tags=["Autocomplete"],
        summary="Autocomplete Map Codes",
        description=(
            "Return a list of map codes ordered by exact match, prefix match, or similarity. "
            "Results can be filtered by archived/hidden status or playtest status."
        ),
    )
    async def get_similar_map_codes(  # noqa: PLR0913
        self,
        autocomplete: AutocompleteRepository,
        search: str,
        archived: bool | None = None,
        hidden: bool | None = None,
        playtesting: PlaytestStatus | None = None,
        limit: int = 5,
    ) -> list[OverwatchCode] | None:
        """Get similar map codes.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to compare.
            archived (bool | None, optional): Filter by archived flag, or `None` for no filter.
            hidden (bool | None, optional): Filter by hidden flag, or `None` for no filter.
            playtesting (PlaytestStatus | None, optional): Filter by playtesting status, or `None` for no filter.
            limit (int, optional): Maximum number of results. Defaults to 5.

        Returns:
            list[OverwatchCode] | None: Matching map codes, or `None` if none found.

        """
        return await autocomplete.get_similar_map_codes(search, archived, hidden, playtesting, limit)

    @get(
        path="/transformers/codes",
        tags=["Transformer"],
        media_type=MediaType.JSON,
        summary="Transform Map Code",
        description=(
            "Transform a free-form input string into the closest matching map code. "
            "Results may be filtered by archived, hidden, or playtest status."
        ),
    )
    async def transform_map_codes(
        self,
        autocomplete: AutocompleteRepository,
        search: str,
        archived: bool | None = None,
        hidden: bool | None = None,
        playtesting: PlaytestStatus | None = None,
    ) -> OverwatchCode | None:
        """Transform a map name into a code.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to transform.
            archived (bool | None, optional): Filter by archived flag, or `None` for no filter.
            hidden (bool | None, optional): Filter by hidden flag, or `None` for no filter.
            playtesting (PlaytestStatus | None, optional): Filter by playtesting status, or `None` for no filter.

        Returns:
            OverwatchCode | None: The closest matching map code, or `None` if none found.

        """
        return await autocomplete.transform_map_codes(search, archived, hidden, playtesting)

    @get(
        path="/autocomplete/users",
        tags=["Autocomplete"],
        summary="Autocomplete Users",
        description=(
            "Return a list of users ordered by text similarity to the provided search string. "
            "Considers nickname, global name, and Overwatch usernames."
        ),
    )
    async def get_similar_users(
        self,
        autocomplete: AutocompleteRepository,
        search: str,
        limit: int = 10,
        fake_users_only: bool = False,
    ) -> list[tuple[int, str]] | None:
        """Get similar users by nickname, global name, or Overwatch username.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to compare.
            limit (int, optional): Maximum number of results. Defaults to 10.
            fake_users_only (bool): Filter out actualy discord users and display fake members only.

        Returns:
            list[tuple[int, str]] | None: A list of `(user_id, display_name)` tuples, or `None` if no matches found.

        """
        return await autocomplete.get_similar_users(search, limit, fake_users_only)

    @get(
        path="/autocomplete/tags",
        tags=["Autocomplete"],
        summary="Autocomplete Map Tags",
        description="Return a list of map tags ordered by text similarity to the provided search string.",
    )
    async def get_similar_map_tags(
        self, autocomplete: AutocompleteRepository, search: str, limit: int = 5
    ) -> list[Tags] | None:
        """Get similar map tags.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): The input string to compare.
            limit (int, optional): Maximum number of results. Defaults to 5.

        Returns:
            list[Tags] | None: A list of matching map tags or `None` if no matches found.

        """
        return await autocomplete.get_similar_map_tags(search, limit)

    @get(
        path="/transformers/tags",
        tags=["Transformer"],
        media_type=MediaType.JSON,
        summary="Transform Map Tag",
        description="Transform a free-form input string into the closest matching Tags name.",
    )
    async def transform_map_tags(self, autocomplete: AutocompleteRepository, search: str) -> Tags | None:
        """Transform a map name into a Tags.

        Args:
            autocomplete (AutocompleteRepository): Autocomplete and transform service.
            search (str): Input string to transform.

        Returns:
            Tags | None: The closest matching map tag, or `None` if no matches found.

        """
        return await autocomplete.transform_map_tags(search)
