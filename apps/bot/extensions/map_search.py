from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from functools import partial
from logging import getLogger
from typing import TYPE_CHECKING, Literal, Sequence, cast, get_args

from discord import ButtonStyle, app_commands, ui
from genjishimada_sdk.difficulties import DifficultyTop
from genjishimada_sdk.maps import GuideURL, MapCategory, Mechanics, OverwatchCode, OverwatchMap, Restrictions, Tags

from extensions.api_service import CompletionFilter, MedalFilter, OfficialFilter, PlaytestFilter
from utilities import transformers
from utilities.base import BaseCog
from utilities.emojis import generate_all_star_rating_strings
from utilities.errors import UserFacingError
from utilities.formatter import FilteredFormatter, FormattableProtocol
from utilities.maps import MapModel
from utilities.paginator import ApiPaginatorView, PaginatorView
from utilities.views.mod_guides_view import FormattableGuide

if TYPE_CHECKING:
    from core import Genji
    from utilities._types import GenjiItx

log = getLogger(__name__)

CN_TRANSLATIONS_TEMP = {
    "Aatlis": "Aatlis",
    "Ayutthaya": "阿育陀耶",
    "Antarctic Peninsula": "南极半岛",
    "Arena Victoriae": "Arena Victoriae",
    "Gogadoro": "Gogadoro",
    "Redwood Dam": "Redwood Dam",
    "Place Lacroix": "Place Lacroix",
    "Black Forest": "黑森林",
    "Black Forest Winter": "圣诞节黑森林",
    "Blizzard World": "暴雪世界",
    "Blizzard World Winter": "圣诞节暴雪世界",
    "Busan": "釜山",
    "Busan Downtown Lunar New Year": "春节釜山城区",
    "Busan Sanctuary Lunar New Year": "春节釜山寺院",
    "Busan Stadium": "釜山体育场",
    "Busan Stadium Classic": "釜山体育场（经典）",  # noqa: RUF001
    "Castillo": "城堡",
    "Chateau Guillard": "吉拉德堡",
    "Chateau Guillard Halloween": "万圣节吉拉德堡",
    "Circuit Royal": "皇家赛道",
    "Colosseo": "斗兽场",
    "Dorado": "多拉多",
    "Ecopoint: Antarctica": "生态监测站：南极洲",  # noqa: RUF001
    "Ecopoint: Antarctica Winter": "圣诞节生态监测站：南极洲",  # noqa: RUF001
    "Eichenwalde": "艾兴瓦尔德",
    "Eichenwalde Halloween": "万圣节艾兴瓦尔德",
    "Esperanca": "埃斯佩兰萨",
    "Estadio das Ras": "弗格体育场",
    "Hanamura": "花村",
    "Hanamura Winter": "圣诞节花村",
    "Hanaoka": "花冈",
    "Havana": "哈瓦那",
    "Hollywood": "好莱坞",
    "Hollywood Halloween": "万圣节好莱坞",
    "Horizon Lunar Colony": "“地平线”月球基地",
    "Ilios": "伊利奥斯",
    "Ilios Lighthouse": "伊利奥斯灯塔",
    "Ilios Ruins": "伊利奥斯废墟",
    "Ilios Well": "伊利奥斯深井",
    "Junkenstein's Revenge": "怪鼠复仇",
    "Junkertown": "渣客镇",
    "Kanezaka": "铁坂",
    "King's Row": "国王大道",
    "King's Row Winter": "圣诞节国王大道",
    "Lijiang Control Center": "漓江塔控制中心",
    "Lijiang Control Center Lunar New Year": "春节漓江塔控制中心",
    "Lijiang Garden": "漓江塔庭院",
    "Lijiang Garden Lunar New Year": "春节漓江塔庭院",
    "Lijiang Night Market": "漓江塔夜市",
    "Lijiang Night Market Lunar New Year": "春节漓江塔夜市",
    "Lijiang Tower": "漓江塔",
    "Lijiang Tower Lunar New Year": "春节漓江塔",
    "Malevento": "马莱温多",
    "Midtown": "中城",
    "Necropolis": "墓园",
    "Nepal": "尼泊尔",
    "Nepal Sanctum": "尼泊尔圣所",
    "Nepal Shrine": "尼泊尔圣坛",
    "Nepal Village": "尼泊尔村庄",
    "Nepal Village Winter": "圣诞节尼泊尔村庄",
    "New Junk City": "新渣客城",
    "New Queen Street": "新皇后街",
    "Numbani": "努巴尼",
    "Oasis": "绿洲城",
    "Oasis City Center": "绿洲城中心",
    "Oasis Gardens": "绿洲城花园",
    "Oasis University": "绿洲城大学",
    "Paraíso": "帕拉伊苏",
    "Paris": "巴黎",
    "Petra": "佩特拉",
    "Practice Range": "训练靶场",
    "Rialto": "里阿尔托",
    "Route 66": "66号公路",
    "Runasapi": "鲁纳塞彼",
    "Samoa": "萨摩亚",
    "Shambali Monastery": "香巴里寺院",
    "Suravasa": "苏拉瓦萨",
    "Sydney Harbour Arena": "悉尼海港竞技场",
    "Sydney Harbour Arena Classic": "悉尼海港竞技场（经典）",  # noqa: RUF001
    "Temple of Anubis": "阿努比斯神殿",
    "Throne of Anubis": "阿努比斯王座",
    "Volskaya Industries": "沃斯卡娅工业区",
    "Watchpoint: Gibraltar": "监测站：直布罗陀",  # noqa: RUF001
    "Workshop Chamber": "地图工坊室内",
    "Workshop Expanse": "地图工坊空地",
    "Workshop Expanse Night": "地图工坊空地（夜间）",  # noqa: RUF001
    "Workshop Green Screen": "地图工坊绿幕",
    "Workshop Island": "地图工坊岛屿",
    "Workshop Island Night": "地图工坊岛屿（夜间）",  # noqa: RUF001
}
CN_TRANSLATIONS_FIELDS_TEMP = {
    "Code": "代码",
    "Global Code": "国际服代码",
    "Global": "官方的",
    "Chinese Code": "国服代码",
    "Title": "标题",
    "Creator": "作者",
    "Map": "地图名",
    "Category": "类别",
    "Checkpoints": "检查点数",
    "Difficulty": "难度",
    "Mechanics": "技巧",
    "Restrictions": "封禁",
    "Guide": "路线",
    "Medals": "奖章",
    "Desc": "描述",
}


_CNTriFilter = Literal["全部", "包含", "不包含"]
CNCompletionFilter = _CNTriFilter
CNMedalFilter = _CNTriFilter
CNPlaytestFilter = Literal["全部", "仅有的", "没有任何"]
CNOfficialFilter = Literal["全部", "仅限官方", "非官方（CN）"]  # noqa: RUF001

CN_FILTER_TRANSLATIONS_TEMP: dict[_CNTriFilter, CompletionFilter] = {
    "全部": "All",
    "包含": "With",
    "不包含": "Without",
}

CN_FILTER_2_TRANSLATIONS_TEMP: dict[OfficialFilter, CNOfficialFilter] = {
    "All": "全部",
    "Global Only": "仅限官方",
    "Chinese Only": "非官方（CN）",  # noqa: RUF001
}

CN_FILTER_3_TRANSLATION_TEMP: dict[CNPlaytestFilter, PlaytestFilter] = {
    "全部": "All",
    "仅有的": "Only",
    "没有任何": "None",
}


class CNTranslatedFilteredFormatter(FilteredFormatter):
    def __init__(
        self,
        model: FormattableProtocol,
        *,
        value_wrap_character: str = "`",
        filter_fields: Sequence[str] | None = None,
    ) -> None:
        """Initialize the formatter.

        Args:
            model: A model that implements FormattableProtocol.
            value_wrap_character: Character used to wrap values.
            filter_fields: Fields to filter out of the foramtter.
        """
        super().__init__(model, value_wrap_character=value_wrap_character, filter_fields=filter_fields)

    def format(self) -> str:
        """Format a Formattable model.

        This is used for Discord embed beautification.

        Returns:
            str: The formatted string.
        """
        if self.values.get("Map", None):
            assert self.values["Map"]
            name = self.values["Map"]
            self.values["Map"] = CN_TRANSLATIONS_TEMP.get(name.replace("(", "").replace(")", ""), name)
        self.values = {CN_TRANSLATIONS_FIELDS_TEMP.get(key, key): value for key, value in self.values.items()}

        return super().format()


class MapSearchView(ApiPaginatorView[MapModel]):
    def __init__(
        self,
        fetch_func: Callable[..., Awaitable[list[MapModel]]],
        *,
        page_size: int = 5,
        enable_cn_translation: bool = False,
    ) -> None:
        """Initialize MapSearchView Paginator with API pagination.

        Args:
            fetch_func: Partial-bound API method that accepts page_number and page_size.
            page_size: Amount of Models on a single page.
            enable_cn_translation (bool, defaults to False): Enable Chinese translations.
        """
        self.enable_cn_translation = enable_cn_translation
        super().__init__(
            "Map Search",
            fetch_func,
            page_size=page_size,
            empty_message="There are no maps with the selected filters.",
        )

    def build_completion_text(self, _map: MapModel) -> str:
        """Return a 'Completed' string with optional medal, based on time + medal thresholds."""
        if _map.time is None:
            return ""

        res = " ✓ Completed"

        medal_label = None
        medals = _map.medals

        if medals:
            t = _map.time

            if medals.gold is not None and t < medals.gold:
                medal_label = "Gold"
            elif medals.silver is not None and t < medals.silver:
                medal_label = "Silver"
            elif medals.bronze is not None and t < medals.bronze:
                medal_label = "Bronze"

        if medal_label:
            res += f" | 🗸 {medal_label}"

        return res

    def build_page_body(self) -> Sequence[ui.Item]:
        """Build page body for MapSearchView."""
        data = self.get_current_page_data()
        res = []
        for _map in data:
            completion_text = self.build_completion_text(_map)

            title = f"### {_map.title}" if _map.title is not None else ""
            code_block = f"\n```{_map.code} {completion_text}```\n"
            if self.enable_cn_translation:
                details = CNTranslatedFilteredFormatter(_map, filter_fields=("Code", "Title")).format()
            else:
                details = FilteredFormatter(_map, filter_fields=("Code", "Title")).format()
            section = (
                ui.TextDisplay(f"{title}{code_block}{details}"),
                ui.Separator(),
            )
            res.extend(section)
        return res


class GuideURLButton(ui.Button):
    def __init__(self, url: GuideURL) -> None:
        """Initialize a guide URL button.

        Creates a button labeled “View” that links directly to the given guide URL.

        Args:
            url: The external guide URL to link to.
        """
        super().__init__(label="View", style=ButtonStyle.url, url=url)


class MapGuideView(PaginatorView[FormattableGuide]):
    def __init__(self, code: OverwatchCode, data: Sequence[FormattableGuide], *, page_size: int = 5) -> None:
        """Initialize a map guide pagination view.

        Sets up a paginated view of guides for a specific map code. Each page
        contains up to `page_size` guides, rendered with thumbnails and buttons.

        Args:
            code: The Overwatch map code the guides belong to.
            data: The sequence of formattable guides to display.
            page_size: Number of guides per page. Defaults to 5.
        """
        self.code = code
        super().__init__(f"{code} - Guides", data, page_size=page_size)

    def build_page_body(self) -> Sequence[ui.Item]:
        """Build the paginator body."""
        data = self.current_page
        res = []
        for guide in data:
            assert guide.thumbnail
            section = (
                ui.Section(
                    ui.TextDisplay(FilteredFormatter(guide, filter_fields=["url"]).format()),
                    accessory=ui.Thumbnail(guide.thumbnail),
                ),
                ui.ActionRow(GuideURLButton(guide.url)),
                ui.Separator(),
            )
            res.extend(section)
        return res


class MapSearchCog(BaseCog):
    @app_commands.command(name="map-search")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    @app_commands.choices(
        difficulty=[app_commands.Choice(name=d, value=d) for d in get_args(DifficultyTop)],
        minimum_quality=[
            app_commands.Choice(name=s, value=i + 1) for i, s in enumerate(generate_all_star_rating_strings())
        ],
        tag=[app_commands.Choice(name=t, value=t) for t in get_args(Tags)],
    )
    async def map_search(  # noqa: PLR0913
        self,
        itx: GenjiItx,
        map_name: app_commands.Transform[OverwatchMap, transformers.MapNameTransformer] | None,
        difficulty: app_commands.Choice[str] | None,
        code: app_commands.Transform[OverwatchCode, transformers.CodeVisibleTransformer] | None,
        creator: app_commands.Transform[int, transformers.UserTransformer] | None,
        mechanic: app_commands.Transform[Mechanics, transformers.MechanicsTransformer] | None,
        restriction: app_commands.Transform[Restrictions, transformers.RestrictionsTransformer] | None,
        tag: app_commands.Choice[str] | None,
        minimum_quality: app_commands.Choice[int] | None,
        category: MapCategory | None,
        official_filter: OfficialFilter = "Global Only",
        completion_filter: CompletionFilter = "All",
        medal_filter: MedalFilter = "All",
        playtest_filter: PlaytestFilter = "All",
    ) -> None:
        """Search for maps with filters such as name, code, difficulty, quality, and more.

        Runs a query against the API using the provided filters and displays the
        results in a paginated view. Supports filtering by restrictions, mechanics,
        tags, playtest/medal/completion state, and category.

        Args:
            itx: The command interaction context.
            map_name: Optional map name filter.
            difficulty: Optional exact difficulty choice.
            code: Optional map code filter.
            creator: Optional creator user ID.
            mechanic: Optional mechanic filter.
            restriction: Optional restriction filter.
            tag: Optional tag filter.
            minimum_quality: Optional minimum star rating filter.
            category: Optional category filter.
            official_filter: Optional official map filter. Defaults to "Official Only".
            completion_filter: Filter maps by completion state. Defaults to "All".
            medal_filter: Filter maps by medal availability. Defaults to "All".
            playtest_filter: Filter imaps by playtest state. Defaults to "All".
        """
        await itx.response.defer(ephemeral=True)
        restrictions: list[Restrictions] | None = [restriction] if restriction else None
        mechanics: list[Mechanics] | None = [mechanic] if mechanic else None
        tags: list[Tags] | None = [cast("Tags", tag.value)] if tag else None
        if official_filter == "All":
            official_val = None
        elif official_filter == "Global Only":
            official_val = True
        else:
            official_val = False

        view = MapSearchView(
            fetch_func=partial(
                self.bot.api.get_maps,
                map_name=[map_name] if map_name else None,
                code=code,
                official=official_val,
                restrictions=restrictions,
                mechanics=mechanics,
                tags=tags,
                difficulty_exact=cast("DifficultyTop", difficulty.value) if difficulty else None,
                minimum_quality=minimum_quality.value if minimum_quality else None,
                creator_ids=[creator] if creator else None,
                playtest_filter=playtest_filter,
                medal_filter=medal_filter,
                completion_filter=completion_filter,
                category=[category] if category else None,
                return_all=False,
                user_id=itx.user.id,
                archived=False,
                hidden=False,
            ),
            page_size=5,
        )
        await view.initialize()
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @app_commands.command(name="地图搜索")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    @app_commands.choices(
        difficulty=[app_commands.Choice(name=d, value=d) for d in get_args(DifficultyTop)],
        minimum_quality=[
            app_commands.Choice(name=s, value=i + 1) for i, s in enumerate(generate_all_star_rating_strings())
        ],
        tag=[app_commands.Choice(name=t, value=t) for t in get_args(Tags)],
    )
    @app_commands.rename(
        map_name="地图名",
        difficulty="难度",
        code="代码",
        creator="作者",
        mechanic="技巧",
        restriction="封禁",
        tag="标签",
        minimum_quality="最低分",
        category="类别",
        official_filter="服务器筛选",
        completion_filter="完成状态",
        medal_filter="奖牌过滤",
    )
    @app_commands.describe(
        map_name="可选过滤特定地图",
        difficulty="可选具体地图难度",
        code="可选地图代码",
        creator="可选地图作者用户名 或 Discord ID",
        mechanic="可选地图使用到的特定技巧",
        restriction="可选地图封禁了哪些技巧",
        tag="可选地图标签",
        minimum_quality="可选地图最低不低于多少评分",
        category="可选地图类别",
        official_filter="可选显示国际服地图, 默认只显示国服地图",
        completion_filter='按照地图完成情况过滤, 默认为"全部"',
        medal_filter='按照是否发放奖牌过滤地图, 默认为"全部"',
    )
    async def map_search_cn(  # noqa: PLR0913
        self,
        itx: GenjiItx,
        map_name: app_commands.Transform[OverwatchMap, transformers.MapNameTransformer] | None,
        difficulty: app_commands.Choice[str] | None,
        code: app_commands.Transform[OverwatchCode, transformers.CodeVisibleTransformer] | None,
        creator: app_commands.Transform[int, transformers.UserTransformer] | None,
        mechanic: app_commands.Transform[Mechanics, transformers.MechanicsTransformer] | None,
        restriction: app_commands.Transform[Restrictions, transformers.RestrictionsTransformer] | None,
        tag: app_commands.Choice[str] | None,
        minimum_quality: app_commands.Choice[int] | None,
        category: MapCategory | None,
        official_filter: CNOfficialFilter = "非官方（CN）",  # noqa: RUF001
        completion_filter: CNCompletionFilter = "全部",
        medal_filter: CNMedalFilter = "全部",
        playtest_filter: CNPlaytestFilter = "全部",
    ) -> None:
        """Search for maps with filters such as name, code, difficulty, quality, and more.

        Runs a query against the API using the provided filters and displays the
        results in a paginated view. Supports filtering by restrictions, mechanics,
        tags, playtest/medal/completion state, and category.

        Args:
            itx: The command interaction context.
            map_name: Optional map name filter..
            difficulty: Optional exact difficulty choice.
            code: Optional map code filter.
            creator: Optional creator user ID.
            mechanic: Optional mechanic filter.
            restriction: Optional restriction filter.
            tag: Optional tag filter.
            minimum_quality: Optional minimum star rating filter.
            category: Optional category filter.
            official_filter: Optional official map filter. Defaults to "Official Only".
            completion_filter: Filter maps by completion state. Defaults to "All".
            medal_filter: Filter maps by medal availability. Defaults to "All".
            playtest_filter: Filter maps by playtest state. Defaults to "All".
        """
        await itx.response.defer(ephemeral=True)
        restrictions: list[Restrictions] | None = [restriction] if restriction else None
        mechanics: list[Mechanics] | None = [mechanic] if mechanic else None
        tags: list[Tags] | None = [cast("Tags", tag.value)] if tag else None
        if official_filter == CN_FILTER_2_TRANSLATIONS_TEMP["All"]:
            official_val = None
        elif official_filter == CN_FILTER_2_TRANSLATIONS_TEMP["Global Only"]:
            official_val = True
        else:
            official_val = False

        view = MapSearchView(
            fetch_func=partial(
                self.bot.api.get_maps,
                map_name=[map_name] if map_name else None,
                code=code,
                official=official_val,
                restrictions=restrictions,
                mechanics=mechanics,
                tags=tags,
                difficulty_exact=cast("DifficultyTop", difficulty.value) if difficulty else None,
                minimum_quality=minimum_quality.value if minimum_quality else None,
                creator_ids=[creator] if creator else None,
                playtest_filter=CN_FILTER_3_TRANSLATION_TEMP[playtest_filter],
                medal_filter=CN_FILTER_TRANSLATIONS_TEMP[medal_filter],
                completion_filter=CN_FILTER_TRANSLATIONS_TEMP[completion_filter],
                category=[category] if category else None,
                return_all=False,
                user_id=itx.user.id,
                archived=False,
                hidden=False,
            ),
            page_size=5,
            enable_cn_translation=True,
        )
        await view.initialize()
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @app_commands.command(name="view-guides")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    async def view_guides(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeVisibleTransformer],
        include_records: bool = False,
    ) -> None:
        """View guides for a particular map code.

        Args:
            itx (GenjiItx): Discord interaction.
            code (OverwatchCode): The map code.
            include_records (bool): Whether to include submitted records in the search.
        """
        await itx.response.defer(ephemeral=True)
        guides = await self.bot.api.get_guides(code, include_records)
        for guide in guides:
            guide.thumbnail = await self.bot.thumbnail_service.get_thumbnail(guide.url)
        if not guides:
            raise UserFacingError("There are no guides for this map.")
        view = MapGuideView(code, guides)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx


async def setup(bot: Genji) -> None:
    """Load the MapSearchCog cog."""
    await bot.add_cog(MapSearchCog(bot))


async def teardown(bot: Genji) -> None:
    """Unload the MapSearchCog cog."""
    await bot.remove_cog("MapSearchCog")
