from __future__ import annotations

import os
from enum import Enum
from http import HTTPStatus
from logging import getLogger
from typing import TYPE_CHECKING, Any, Literal, Sequence, cast, get_args

import discord
from aio_pika.abc import AbstractIncomingMessage
from discord import ButtonStyle, Member, SelectOption, TextStyle, app_commands, ui
from discord.ui import LayoutView
from genjishimada_sdk.completions import CompletionModerateRequest
from genjishimada_sdk.difficulties import DIFFICULTY_RANGES_ALL, DifficultyAll
from genjishimada_sdk.maps import (
    LinkMapsCreateRequest,
    MapCategory,
    MapEditCreatedEvent,
    MapEditCreateRequest,
    MapEditResolvedEvent,
    MapEditResolveRequest,
    MapEditSetMessageIdRequest,
    MapEditSubmissionResponse,
    MapPatchRequest,
    Mechanics,
    MedalsResponse,
    OverwatchCode,
    OverwatchMap,
    PlaytestStatus,
    QualityValueRequest,
    Restrictions,
    SendToPlaytestRequest,
    Tags,
    UnlinkMapsCreateRequest,
)
from msgspec import UNSET

from extensions._queue_registry import queue_consumer
from extensions.completions import CompletionLeaderboardFormattable
from utilities import transformers
from utilities.base import BaseCog, BaseService, BaseView, ConfirmationView
from utilities.emojis import generate_all_star_rating_strings, stars_rating_string
from utilities.errors import APIHTTPError, UserFacingError
from utilities.formatter import FilteredFormatter
from utilities.paginator import PaginatorView
from utilities.views.mod_creator_view import MapCreatorModView
from utilities.views.mod_guides_view import ModGuidePaginatorView
from utilities.views.mod_status_view import ModStatusView

if TYPE_CHECKING:
    from core import Genji
    from utilities._types import GenjiItx
    from utilities.maps import MapModel

log = getLogger(__name__)


class ModeratorCog(BaseCog):
    mod = app_commands.Group(
        name="mod", description="Mod only commands", guild_ids=[int(os.getenv("DISCORD_GUILD_ID", "0"))]
    )
    map = app_commands.Group(
        name="map", description="Mod only commands", parent=mod, guild_ids=[int(os.getenv("DISCORD_GUILD_ID", "0"))]
    )
    record = app_commands.Group(
        name="edit-record",
        description="Mod only commands",
        parent=mod,
        guild_ids=[int(os.getenv("DISCORD_GUILD_ID", "0"))],
    )
    user = app_commands.Group(
        name="edit-user",
        description="Mod only commands",
        parent=mod,
        guild_ids=[int(os.getenv("DISCORD_GUILD_ID", "0"))],
    )

    @map.command(name="edit")
    async def edit_map(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Edit a map directly (Mod only).

        Args:
            itx: The interaction context.
            code: The map code to edit.
        """
        await itx.response.defer(ephemeral=True)

        # Check mod permissions
        assert isinstance(itx.user, discord.Member) and itx.guild
        is_mod = (
            itx.user.get_role(itx.client.config.roles.admin.mod) is not None
            or itx.user.get_role(itx.client.config.roles.admin.sensei) is not None
        )

        if not is_mod:
            raise UserFacingError("This command is for moderators only. Use `/suggest-edit` instead.")

        # Fetch map data
        map_data = await itx.client.api.get_map(code=code)
        if not map_data:
            raise UserFacingError(f"Map `{code}` not found.")

        # Start wizard in mod mode
        view = MapEditWizardView(map_data, is_mod=True)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @map.command(name="edit-guides")
    async def edit_delete_guides(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Open guide removal interface for a specific map.

        Args:
            itx (GenjiItx): The interaction context.
            code (OverwatchCode): The map code to modify.
        """
        await itx.response.defer(ephemeral=True)
        guides = await itx.client.api.get_guides(code)
        if not guides:
            raise UserFacingError("There are no guides for this map.")
        view = ModGuidePaginatorView(code, guides, itx.client)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @map.command(name="edit-creators")
    async def edit_delete_creators(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Open creator editing interface for a specific map.

        Args:
            itx (GenjiItx): The interaction context.
            code (OverwatchCode): The map code to modify.
        """
        await itx.response.defer(ephemeral=True)
        data = await itx.client.api.get_map(code=code)
        view = MapCreatorModView(data)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @map.command(name="edit-status")
    async def edit_status(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Open interface to edit the verification and playtesting status of a map.

        Args:
            itx (GenjiItx): The interaction context.
            code (OverwatchCode): The map code.
        """
        await itx.response.defer(ephemeral=True)
        data = await itx.client.api.get_map(code=code)
        view = ModStatusView(data)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx
        await view.wait()
        if not view.confirmed:
            return

        playtesting = (
            cast("PlaytestStatus", view.playtest_status_select.values[0])
            if view.playtest_status_select.values
            else UNSET
        )

        await self.bot.api.edit_map(
            code,
            MapPatchRequest(
                hidden=view.hidden_button.enabled,
                official=view.official_button.enabled,
                archived=view.archived_button.enabled,
                playtesting=playtesting,
            ),
        )
        if view.send_to_playtest_button.enabled:
            playtesting_difficulty = cast(DifficultyAll, view.playtest_difficulty_select.values[0])
            await self.bot.api.send_map_to_playtest(data.code, SendToPlaytestRequest(playtesting_difficulty))

    @map.command(name="link-codes")
    async def link_codes(
        self,
        itx: GenjiItx,
        official_code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
        unofficial_code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Link an official and unofficial map.

        Args:
            itx (GenjiItx): The interaction context.
            official_code (OverwatchCode): The official map code to link.
            unofficial_code (OverwatchCode): The unofficial map code to link.

        Raises:
            UserFacingError: If the map could not be retrieved.
        """
        data = LinkMapsCreateRequest(official_code=official_code, unofficial_code=unofficial_code)

        message = (
            f"Are you sure you want to link these two maps?\n`Global` {official_code}\n`Chinese` {unofficial_code}\n"
        )

        async def callback() -> None:
            try:
                await itx.client.api.link_map_codes(data)
            except APIHTTPError as e:
                if e.status == HTTPStatus.BAD_REQUEST:
                    raise UserFacingError()
                raise e

        view = ConfirmationView(message, callback)
        await itx.response.send_message(view=view, ephemeral=True)
        view.original_interaction = itx

    @map.command(name="unlink-codes")
    async def unlink_codes(
        self,
        itx: GenjiItx,
        official_code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
        unofficial_code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
        reason: str,
    ) -> None:
        """Unlink an official and unofficial map.

        Args:
            itx (GenjiItx): The interaction context.
            official_code (OverwatchCode): The official map code to unlink.
            unofficial_code (OverwatchCode): The unofficial map code to unlink.
            reason (str): The reason why it was unlinked.

        """
        data = UnlinkMapsCreateRequest(official_code=official_code, unofficial_code=unofficial_code, reason=reason)

        message = (
            f"Are you sure you want to unlink these two maps?\n`Global` {official_code}\n`Chinese` {unofficial_code}\n"
        )

        async def callback() -> None:
            try:
                await itx.client.api.unlink_map_codes(data)
            except APIHTTPError as e:
                if e.status == HTTPStatus.BAD_REQUEST:
                    raise UserFacingError()
                raise

        view = ConfirmationView(message, callback)
        await itx.response.send_message(view=view, ephemeral=True)
        view.original_interaction = itx

    @user.command(name="create-fake-user")
    async def create_fake_user(self, itx: GenjiItx, name: str) -> None:
        """Create a 'fake' user for submissions.

        This user is not linked to a real Discord account and can be used in test completions or moderation workflows.

        Args:
            itx (GenjiItx): The interaction context.
            name (str): The name of the fake user.

        Raises:
            UserFacingError: If a fake user could not be created.
        """
        await itx.response.defer(ephemeral=True)

        message = f"Are you sure you want to create a fake user with the name: `{name}`?"

        async def callback() -> None:
            await itx.client.api.create_fake_member(name)

        view = ConfirmationView(message, callback)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @user.command(name="link-fake-user")
    async def link_fake_user_to_real(
        self,
        itx: GenjiItx,
        fake_member: app_commands.Transform[int, transformers.FakeUserTransformer],
        real_member: Member,
    ) -> None:
        """Link a previously created fake user to a real user.

        Transfers any data (completions, verifications, etc.) from a fake user to an actual user account.

        Args:
            itx (GenjiItx): The interaction context.
            fake_member (int): Transformed autocomplete user into an user_id
            real_member (Member): The real member to link.

        Raises:
            UserFacingError: If the user IDs are invalid or incompatible.
        """
        await itx.response.defer(ephemeral=True)

        fake_member_data = await self.bot.api.get_user(fake_member)
        if not fake_member_data:
            raise UserFacingError("Fake user was not found.")

        real_member_data = await self.bot.api.get_user(real_member.id)
        if not real_member_data:
            raise UserFacingError("Real user was not found.")
        message = (
            "Are you sure you want to link these members?\n\n"
            f"{fake_member_data.coalesced_name} ({fake_member_data.id}) data will be merged with "
            f"{real_member_data.coalesced_name} ({real_member_data.id})\n"
            f"{fake_member_data.coalesced_name} ({fake_member_data.id}) will be removed after this is confirmed. "
            "This cannot be undone."
        )

        async def callback() -> None:
            await itx.client.api.link_fake_member_id_to_real_user_id(fake_member_data.id, real_member_data.id)

        view = ConfirmationView(message, callback)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @record.command(name="manage")
    async def manage_records(
        self,
        itx: GenjiItx,
        # optional code <- lists all records for code or optionally filtered by a single user
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer] | None,
        # optional user <- lists all records for user or optionally filtered by a single code
        user: app_commands.Transform[int, transformers.UserTransformer] | None,
        verification_status: Literal["Unverified", "Verified", "All"] = "All",
        latest_only: bool = True,
    ) -> None:
        """Manage records for a given user or map.

        Args:
            itx (GenjiItx): The interaction context.
            code (OverwatchCode | None): Optional map code to filter records.
            user (int | None): Optional user ID to filter records.
            verification_status (Literal["Unverified", "Verified", "All"]): Filter records by verification status.
            latest_only (bool): Whether to only show the most recent run per user.
        """
        await itx.response.defer(ephemeral=True)

        # Fetch all records with filters
        records = await itx.client.api.get_records_filtered(
            code=code,
            user_id=user,
            verification_status=verification_status,
            latest_only=latest_only,
            page_size=0,  # Fetch all records
            page_number=1,
        )

        if not records:
            raise UserFacingError("No records found matching the specified filters.")

        # Create and show the mod record view
        view = ModRecordManagementView(records, code, user, verification_status, latest_only)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx


async def setup(bot: Genji) -> None:
    """Load the ModeratorCog cog.

    Args:
        bot (Genji): The bot instance.
    """
    bot.map_editor = MapEditorService(bot)
    await bot.add_cog(ModeratorCog(bot))


async def teardown(bot: Genji) -> None:
    """Unload the ModeratorCog cog.

    Args:
        bot (Genji): The bot instance.
    """
    await bot.remove_cog("ModeratorCog")


class EditableField(str, Enum):
    """Fields that can be edited through the wizard."""

    CODE = "code"
    MAP_NAME = "map_name"
    CATEGORY = "category"
    CHECKPOINTS = "checkpoints"
    DIFFICULTY = "difficulty"
    DESCRIPTION = "description"
    TITLE = "title"
    MECHANICS = "mechanics"
    RESTRICTIONS = "restrictions"
    TAGS = "tags"
    MEDALS = "medals"
    CUSTOM_BANNER = "custom_banner"
    # Mod-only fields (still editable but typically mod-controlled)
    HIDDEN = "hidden"
    ARCHIVED = "archived"
    OFFICIAL = "official"
    CREATORS = "creators"

    SEND_TO_PLAYTEST = "send_to_playtest"
    MAKE_LEGACY = "make_legacy"
    OVERRIDE_RATING = "override_rating"

    @property
    def display_name(self) -> str:
        """Human-readable name."""
        return self.value.replace("_", " ").title()

    @property
    def requires_modal(self) -> bool:
        """Whether this field needs a text input modal."""
        return self in {
            EditableField.CODE,
            EditableField.CHECKPOINTS,
            EditableField.DESCRIPTION,
            EditableField.TITLE,
            EditableField.CUSTOM_BANNER,
        }

    @property
    def requires_select(self) -> bool:
        """Whether this field uses a select menu."""
        return self in {
            EditableField.MAP_NAME,
            EditableField.CATEGORY,
            EditableField.DIFFICULTY,
            EditableField.MECHANICS,
            EditableField.RESTRICTIONS,
            EditableField.TAGS,
        }

    @property
    def requires_toggle(self) -> bool:
        """Whether this field is a boolean toggle."""
        return self in {
            EditableField.HIDDEN,
            EditableField.ARCHIVED,
            EditableField.OFFICIAL,
        }

    @property
    def requires_special(self) -> bool:
        """Whether this field needs special handling."""
        return self in {
            EditableField.MEDALS,
            EditableField.CREATORS,
            EditableField.SEND_TO_PLAYTEST,
            EditableField.MAKE_LEGACY,
            EditableField.OVERRIDE_RATING,
        }


_PREVIEW_MAX_LENGTH = 50
_MOD_ONLY_FIELDS = {
    EditableField.HIDDEN,
    EditableField.SEND_TO_PLAYTEST,
    EditableField.MAKE_LEGACY,
    EditableField.OVERRIDE_RATING,
}
_EXCLUDED_FIELDS = {EditableField.CREATORS}
_PAGINATED_SELECT_PAGE_SIZE = 25
FieldValue = str | int | float | bool | list[str] | MedalsResponse | None


class MapEditWizardState:
    """Tracks the state of a map edit wizard session."""

    def __init__(self, map_data: MapModel, is_mod: bool) -> None:
        """Initialize the wizard state.

        Args:
            map_data: The map being edited.
            is_mod: Whether the user is a moderator.
        """
        self.map_data = map_data
        self.is_mod = is_mod
        self.pending_changes: dict[str, FieldValue] = {}
        self.mod_actions: dict[str, object] = {}
        self.reason: str | None = None
        self.current_step: Literal["select_fields", "edit_field", "review", "reason"] = "select_fields"
        self.selected_fields: list[EditableField] = []
        self.current_field_index: int = 0

    @property
    def current_field(self) -> EditableField | None:
        """Get the field currently being edited."""
        if self.current_field_index < len(self.selected_fields):
            return self.selected_fields[self.current_field_index]
        return None

    def get_current_value(self, field: EditableField) -> FieldValue:
        """Get the current value of a field from the map."""
        return getattr(self.map_data, field.value, None)

    def get_pending_value(self, field: EditableField) -> FieldValue:
        """Get the pending change value, or current if not changed."""
        if field.value in self.pending_changes:
            return self.pending_changes[field.value]
        return self.get_current_value(field)

    def set_change(self, field: EditableField, value: FieldValue) -> None:
        """Record a pending change."""
        self.pending_changes[field.value] = value

    def has_changes(self) -> bool:
        """Check if any changes have been made."""
        return len(self.pending_changes) > 0

    def advance_field(self) -> bool:
        """Move to the next field. Returns False if done with all fields."""
        self.current_field_index += 1
        return self.current_field_index < len(self.selected_fields)

    def get_mod_action(self, field: EditableField) -> object | None:
        """Get the current staged mod action value."""
        return self.mod_actions.get(field.value)

    def set_mod_action(self, field: EditableField, value: object | None) -> None:
        """Record a staged mod action value."""
        if value is None:
            self.mod_actions.pop(field.value, None)
            return
        self.mod_actions[field.value] = value


class FieldSelectionSelect(ui.Select["MapEditWizardView"]):
    """Multi-select for choosing which fields to edit."""

    view: MapEditWizardView

    def __init__(self, map_data: MapModel, *, is_mod: bool) -> None:
        """Initialize the field selection select.

        Args:
            map_data: The map data to build options from.
            is_mod: Whether the user is a moderator.
        """
        options = [
            SelectOption(
                label=field.display_name,
                value=field.value,
                description=self._get_current_preview(map_data, field),
            )
            for field in EditableField
            if field not in _EXCLUDED_FIELDS and (is_mod or field not in _MOD_ONLY_FIELDS)
        ]
        super().__init__(
            placeholder="Select fields to edit...",
            min_values=1,
            max_values=len(options),
            options=options[:25],  # Discord limit
        )

    @staticmethod
    def _get_current_preview(map_data: MapModel, field: EditableField) -> str:
        """Get a short preview of the current value."""
        value = getattr(map_data, field.value, None)
        if value is None:
            return "Not set"
        if isinstance(value, list):
            return f"{len(value)} items" if value else "None"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        preview = str(value)
        return preview[:_PREVIEW_MAX_LENGTH] + "..." if len(preview) > _PREVIEW_MAX_LENGTH else preview

    async def callback(self, itx: GenjiItx) -> None:
        """Handle field selection and advance to editing step."""
        self.view.state.selected_fields = [EditableField(v) for v in self.values]
        self.view.state.current_step = "edit_field"
        self.view.state.current_field_index = 0
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class TextInputModal(ui.Modal):
    """Generic modal for text input fields."""

    value_input: ui.TextInput

    def __init__(self, field: EditableField, current_value: FieldValue) -> None:
        """Initialize the text input modal.

        Args:
            field: The field being edited.
            current_value: The current value of the field.
        """
        super().__init__(title=f"Edit {field.display_name}")
        self.field = field
        self.submitted_value: str | int | None = None

        # Configure based on field type
        style = TextStyle.paragraph if field == EditableField.DESCRIPTION else TextStyle.short
        max_length = 1000 if field == EditableField.DESCRIPTION else 100

        default = str(current_value) if current_value is not None else ""

        self.value_input = ui.TextInput(
            label=field.display_name,
            style=style,
            max_length=max_length,
            default=default,
            required=False,  # Allow clearing
        )
        self.add_item(self.value_input)

    async def on_submit(self, itx: GenjiItx) -> None:
        """Process the submitted value."""
        await itx.response.defer()
        raw_value = self.value_input.value.strip()

        # Type conversion based on field
        if self.field == EditableField.CHECKPOINTS:
            try:
                self.submitted_value = int(raw_value) if raw_value else None
            except ValueError:
                raise UserFacingError("Checkpoints must be a number.")
        elif self.field == EditableField.CODE:
            if raw_value and not raw_value.isalnum():
                raise UserFacingError("Code must be alphanumeric.")
            self.submitted_value = raw_value.upper() if raw_value else None
        else:
            self.submitted_value = raw_value if raw_value else None

        self.stop()


class MedalsModal(ui.Modal):
    """Modal for editing medal thresholds."""

    def __init__(self, current_medals: MedalsResponse | None) -> None:
        """Initialize the medals modal.

        Args:
            current_medals: The current medal thresholds, if any.
        """
        super().__init__(title="Edit Medal Thresholds")
        self.submitted_medals: MedalsResponse | None = None

        gold = current_medals.gold if current_medals else ""
        silver = current_medals.silver if current_medals else ""
        bronze = current_medals.bronze if current_medals else ""

        self.gold_input = ui.TextInput(
            label="Gold (fastest)",
            default=str(gold) if gold else "",
            required=False,
        )
        self.silver_input = ui.TextInput(
            label="Silver",
            default=str(silver) if silver else "",
            required=False,
        )
        self.bronze_input = ui.TextInput(
            label="Bronze (slowest)",
            default=str(bronze) if bronze else "",
            required=False,
        )

        self.add_item(self.gold_input)
        self.add_item(self.silver_input)
        self.add_item(self.bronze_input)

    async def on_submit(self, itx: GenjiItx) -> None:
        """Validate and store medal values."""
        await itx.response.defer()
        gold_str = self.gold_input.value.strip()
        silver_str = self.silver_input.value.strip()
        bronze_str = self.bronze_input.value.strip()

        # If all empty, clear medals
        if not any([gold_str, silver_str, bronze_str]):
            self.submitted_medals = None
            self.stop()
            return

        # All must be provided
        if not all([gold_str, silver_str, bronze_str]):
            raise UserFacingError("All three medal thresholds must be provided, or all must be empty.")

        try:
            gold = float(gold_str)
            silver = float(silver_str)
            bronze = float(bronze_str)
        except ValueError:
            raise UserFacingError("Medal values must be numbers.")

        if not (gold < silver < bronze):
            raise UserFacingError("Gold must be faster than silver, and silver faster than bronze.")

        self.submitted_medals = MedalsResponse(gold=gold, silver=silver, bronze=bronze)

        self.stop()


class DifficultySelect(ui.Select["MapEditWizardView"]):
    """Select for difficulty field."""

    view: MapEditWizardView

    def __init__(self, current: DifficultyAll | None) -> None:
        """Initialize the difficulty select.

        Args:
            current: The current difficulty value.
        """
        options = [SelectOption(label=d, value=d, default=(d == current)) for d in DIFFICULTY_RANGES_ALL]
        super().__init__(placeholder="Select difficulty...", options=options)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle difficulty selection."""
        self.view.state.set_change(EditableField.DIFFICULTY, self.values[0])
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class CategorySelect(ui.Select["MapEditWizardView"]):
    """Select for category field."""

    view: MapEditWizardView

    def __init__(self, current: MapCategory | None) -> None:
        """Initialize the category select.

        Args:
            current: The current category value.
        """
        options = [SelectOption(label=c, value=c, default=(c == current)) for c in get_args(MapCategory)]
        super().__init__(placeholder="Select category...", options=options)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle category selection."""
        self.view.state.set_change(EditableField.CATEGORY, self.values[0])
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class MapNameSelect(ui.Select["MapEditWizardView"]):
    """Paginated select for map name field."""

    view: MapEditWizardView

    def __init__(self, current: OverwatchMap | None, page: int = 0) -> None:
        """Initialize the map name select.

        Args:
            current: The current map name value.
            page: The current page (0-indexed).
        """
        all_maps = list(get_args(OverwatchMap))
        all_maps.sort()  # Sort alphabetically for easier navigation

        start_idx = page * _PAGINATED_SELECT_PAGE_SIZE
        end_idx = start_idx + _PAGINATED_SELECT_PAGE_SIZE
        page_maps = all_maps[start_idx:end_idx]

        options = [SelectOption(label=m, value=m, default=(m == current)) for m in page_maps]
        placeholder = f"Select map name (page {page + 1})..."
        super().__init__(placeholder=placeholder, options=options)
        self.page = page
        self.total_pages = (len(all_maps) + _PAGINATED_SELECT_PAGE_SIZE - 1) // _PAGINATED_SELECT_PAGE_SIZE

    async def callback(self, itx: GenjiItx) -> None:
        """Handle map name selection."""
        self.view.state.set_change(EditableField.MAP_NAME, self.values[0])
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        # Reset page state when selection is made
        self.view.map_name_page = 0
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class MapNamePageButton(ui.Button["MapEditWizardView"]):
    """Button to navigate map name pages."""

    view: MapEditWizardView

    def __init__(self, direction: Literal["prev", "next"], *, disabled: bool = False) -> None:
        """Initialize the page navigation button.

        Args:
            direction: Whether this is a previous or next button.
            disabled: Whether the button should be disabled.
        """
        self.direction = direction
        label = "◀ Previous" if direction == "prev" else "Next ▶"
        super().__init__(label=label, style=ButtonStyle.secondary, disabled=disabled)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle page navigation."""
        if self.direction == "prev":
            self.view.map_name_page = max(0, self.view.map_name_page - 1)
        else:
            self.view.map_name_page += 1
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class MechanicsSelect(ui.Select["MapEditWizardView"]):
    """Multi-select for mechanics."""

    view: MapEditWizardView

    def __init__(self, current: list[Mechanics]) -> None:
        """Initialize the mechanics select.

        Args:
            current: The current list of mechanics.
        """
        options = [SelectOption(label=m, value=m, default=(m in current)) for m in get_args(Mechanics)[:25]]
        super().__init__(
            placeholder="Select mechanics...",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Handle mechanics selection."""
        self.view.state.set_change(EditableField.MECHANICS, list(self.values))
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class RestrictionsSelect(ui.Select["MapEditWizardView"]):
    """Multi-select for restrictions."""

    view: MapEditWizardView

    def __init__(self, current: list[Restrictions]) -> None:
        """Initialize the restrictions select.

        Args:
            current: The current list of restrictions.
        """
        options = [SelectOption(label=r, value=r, default=(r in current)) for r in get_args(Restrictions)]
        super().__init__(
            placeholder="Select restrictions...",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Handle restrictions selection."""
        self.view.state.set_change(EditableField.RESTRICTIONS, list(self.values))
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"

        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class TagsSelect(ui.Select["MapEditWizardView"]):
    """Multi-select for tags."""

    view: MapEditWizardView

    def __init__(self, current: list[Tags]) -> None:
        """Initialize the tags select.

        Args:
            current: The current list of tags.
        """
        options = [SelectOption(label=t, value=t, default=(t in current)) for t in get_args(Tags)]
        super().__init__(
            placeholder="Select tags...",
            min_values=0,
            max_values=len(options),
            options=options,
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Handle tags selection."""
        self.view.state.set_change(EditableField.TAGS, list(self.values))
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"

        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class PlaytestDifficultySelect(ui.Select["MapEditWizardView"]):
    """Select to send a map back to playtest (mod-only action)."""

    view: MapEditWizardView

    def __init__(self, current: DifficultyAll | None) -> None:
        """Initialize the playtest difficulty select.

        Args:
            current: The currently selected playtest difficulty, if any.
        """
        options = [SelectOption(label=d, value=d, default=(d == current)) for d in DIFFICULTY_RANGES_ALL]
        super().__init__(placeholder="Select playtest difficulty...", options=options)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle difficulty selection and stage send-to-playtest action.

        Args:
            itx: The interaction context.
        """
        self.view.state.set_mod_action(EditableField.SEND_TO_PLAYTEST, self.values[0])
        if not self.view.state.advance_field():
            self.view.state.current_step = "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class RatingOverrideSelect(ui.Select["MapEditWizardView"]):
    """Select to override map rating (mod-only action)."""

    view: MapEditWizardView

    def __init__(self, current: int | None) -> None:
        """Initialize the rating override select.

        Args:
            current: The currently selected override rating, if any.
        """
        strings = generate_all_star_rating_strings()
        options: list[SelectOption] = []
        for i, s in enumerate(strings, start=1):
            options.append(
                SelectOption(
                    label=s,
                    value=str(i),
                    default=(i == current),
                )
            )
        super().__init__(placeholder="Select rating override...", options=options)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle rating selection and stage rating override action.

        Args:
            itx: The interaction context.
        """
        self.view.state.set_mod_action(EditableField.OVERRIDE_RATING, int(self.values[0]))
        if not self.view.state.advance_field():
            self.view.state.current_step = "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class ModBooleanToggleButton(ui.Button["MapEditWizardView"]):
    """Toggle button for mod-only boolean actions (not patch fields)."""

    view: MapEditWizardView

    def __init__(self, field: EditableField, current: bool) -> None:
        """Initialize the mod-only boolean toggle button.

        Args:
            field: The mod-only action field being toggled.
            current: The current boolean value.
        """
        self.field = field
        self.current_value = current
        label = f"{field.display_name}: {'Yes' if current else 'No'}"
        style = ButtonStyle.green if current else ButtonStyle.red
        super().__init__(label=label, style=style)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle toggle interaction and stage mod-only action.

        Args:
            itx: The interaction context.
        """
        new_value = not self.current_value
        # One-way semantics are enforced at submit-time: only act when True.
        self.view.state.set_mod_action(self.field, new_value)
        if not self.view.state.advance_field():
            self.view.state.current_step = "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class BooleanToggleButton(ui.Button["MapEditWizardView"]):
    """Toggle button for boolean fields."""

    view: MapEditWizardView

    def __init__(self, field: EditableField, current: bool) -> None:
        """Initialize the boolean toggle button.

        Args:
            field: The field being toggled.
            current: The current boolean value.
        """
        self.field = field
        self.current_value = current
        label = f"{field.display_name}: {'Yes' if current else 'No'}"
        style = ButtonStyle.green if current else ButtonStyle.red
        super().__init__(label=label, style=style)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle boolean toggle."""
        new_value = not self.current_value
        self.view.state.set_change(self.field, new_value)
        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class OpenModalButton(ui.Button["MapEditWizardView"]):
    """Button to open a text input modal."""

    view: MapEditWizardView

    def __init__(self, field: EditableField) -> None:
        """Initialize the modal open button.

        Args:
            field: The field to edit via modal.
        """
        self.field = field
        super().__init__(label=f"Edit {field.display_name}", style=ButtonStyle.blurple)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle button click to open modal."""
        current = self.view.state.get_pending_value(self.field)

        if self.field == EditableField.MEDALS:
            medals_modal = MedalsModal(cast(MedalsResponse | None, current))
            await itx.response.send_modal(medals_modal)
            await medals_modal.wait()
            if medals_modal.submitted_medals is not None or current is not None:
                self.view.state.set_change(self.field, medals_modal.submitted_medals)
        else:
            text_modal = TextInputModal(self.field, current)
            await itx.response.send_modal(text_modal)
            await text_modal.wait()
            if text_modal.submitted_value is not None or current is not None:
                self.view.state.set_change(self.field, text_modal.submitted_value)

        if not self.view.state.advance_field():
            self.view.state.current_step = "reason" if not self.view.state.is_mod else "review"
        view = self.view
        self.view.rebuild()
        await itx.edit_original_response(view=view)


class ReasonModal(ui.Modal):
    """Modal for entering the reason for changes."""

    reason_input = ui.TextInput(
        label="Reason for changes",
        style=TextStyle.paragraph,
        placeholder="Explain why these changes should be made...",
        min_length=10,
        max_length=500,
    )

    def __init__(self) -> None:
        """Initialize the reason modal."""
        super().__init__(title="Reason for Edit Request")
        self.submitted_reason: str | None = None

    async def on_submit(self, itx: GenjiItx) -> None:
        """Handle reason submission."""
        self.submitted_reason = self.reason_input.value
        await itx.response.defer()
        self.stop()


class EnterReasonButton(ui.Button["MapEditWizardView"]):
    """Button to open reason modal."""

    view: MapEditWizardView

    def __init__(self) -> None:
        """Initialize the enter reason button."""
        super().__init__(label="Enter Reason", style=ButtonStyle.blurple)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle button click to open reason modal."""
        modal = ReasonModal()
        await itx.response.send_modal(modal)
        await modal.wait()
        if modal.submitted_reason:
            self.view.state.reason = modal.submitted_reason
            self.view.state.current_step = "review"
            view = self.view
            self.view.rebuild()
            await itx.edit_original_response(view=view)


class CancelButton(ui.Button["MapEditWizardView"]):
    """Cancel the wizard."""

    view: MapEditWizardView

    def __init__(self) -> None:
        """Initialize the cancel button."""
        super().__init__(label="Cancel", style=ButtonStyle.red, row=4)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle cancel button click."""
        self.view.cancelled = True
        self.view.stop()
        view = LayoutView()
        view.add_item(ui.Container(ui.TextDisplay("Edit cancelled.")))
        await itx.response.edit_message(view=view)


class BackButton(ui.Button["MapEditWizardView"]):
    """Go back to previous step."""

    view: MapEditWizardView

    def __init__(self) -> None:
        """Initialize the back button."""
        super().__init__(label="Back", style=ButtonStyle.grey, row=4)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle back button click to navigate to previous step."""
        state = self.view.state
        if state.current_step == "edit_field" and state.current_field_index > 0:
            state.current_field_index -= 1
        elif state.current_step == "edit_field":
            state.current_step = "select_fields"
        elif state.current_step == "reason":
            state.current_step = "edit_field"
            state.current_field_index = len(state.selected_fields) - 1
        elif state.current_step == "review":
            if state.is_mod:
                state.current_step = "edit_field"
                state.current_field_index = len(state.selected_fields) - 1
            else:
                state.current_step = "reason"
        view = self.view
        self.view.rebuild()
        await itx.response.edit_message(view=view)


class SubmitButton(ui.Button["MapEditWizardView"]):
    """Submit the edit request."""

    view: MapEditWizardView

    def __init__(self, is_mod: bool, *, disabled: bool = False) -> None:
        """Initialize the submit button.

        Args:
            is_mod: Whether the user is a moderator.
            disabled: Whether the button should be disabled.
        """
        label = "Apply Changes" if is_mod else "Submit for Approval"
        super().__init__(label=label, style=ButtonStyle.green, row=4, disabled=disabled)
        self.is_mod = is_mod

    async def callback(self, itx: GenjiItx) -> None:
        """Handle submit button click to apply or queue changes."""
        await itx.response.defer(ephemeral=True, thinking=True)

        state = self.view.state

        if self.is_mod:
            # Apply mod-only actions (not patch fields)
            playtest_difficulty = cast(
                DifficultyAll | None,
                state.get_mod_action(EditableField.SEND_TO_PLAYTEST),
            )
            if playtest_difficulty is not None:
                await itx.client.api.send_map_to_playtest(
                    state.map_data.code,
                    SendToPlaytestRequest(playtest_difficulty),
                )
            make_legacy = bool(state.get_mod_action(EditableField.MAKE_LEGACY) or False)
            if make_legacy:
                await itx.client.api.convert_map_to_legacy(state.map_data.code)
            override_rating = cast(int | None, state.get_mod_action(EditableField.OVERRIDE_RATING))
            if override_rating is not None:
                await itx.client.api.override_quality_votes(
                    state.map_data.code,
                    QualityValueRequest(value=override_rating),
                )
            # Handle archive separately - use dedicated endpoint for newsfeed
            if "archived" in state.pending_changes:
                archived_value = state.pending_changes["archived"]
                if archived_value:
                    await itx.client.api.archive_map(state.map_data.code)
                else:
                    await itx.client.api.unarchive_map(state.map_data.code)

                # Remove archived from pending changes so it's not sent to patch
                remaining_changes = {k: v for k, v in state.pending_changes.items() if k != "archived"}

                # Apply remaining changes if any
                if remaining_changes:
                    state.pending_changes = remaining_changes
                    patch = self._build_patch_request(state)
                    await itx.client.api.edit_map(state.map_data.code, patch)
            else:
                # No archive change, apply normally
                patch = self._build_patch_request(state)
                await itx.client.api.edit_map(state.map_data.code, patch)

            await itx.edit_original_response(
                content=f"✅ Changes applied to **{state.map_data.code}**!",
                view=None,
            )
        else:
            # Submit for approval
            request = self._build_edit_request(state, itx.user.id)
            try:
                await itx.client.api.create_map_edit_request(request)
            except APIHTTPError as e:
                raise UserFacingError(e.error or "Failed to submit the edit request.")
            await itx.edit_original_response(
                content=(
                    f"✅ Edit request submitted for **{state.map_data.code}**!\nA moderator will review your changes."
                ),
                view=None,
            )

        self.view.submitted = True
        self.view.stop()

    @staticmethod
    def _build_patch_request(state: MapEditWizardState) -> MapPatchRequest:
        """Build a MapPatchRequest from pending changes."""
        kwargs = {}
        for field_name, value in state.pending_changes.items():
            if field_name == "code":
                kwargs["code"] = value
            else:
                kwargs[field_name] = value
        return MapPatchRequest(**kwargs)

    @staticmethod
    def _build_edit_request(state: MapEditWizardState, user_id: int) -> MapEditCreateRequest:
        """Build a MapEditCreateRequest from pending changes."""
        kwargs = {
            "code": state.map_data.code,
            "reason": state.reason or "",
            "created_by": user_id,
        }
        for field_name, value in state.pending_changes.items():
            if field_name == "code":
                kwargs["new_code"] = value
            else:
                kwargs[field_name] = value
        return MapEditCreateRequest(**kwargs)


class MapEditWizardView(BaseView):
    """Main wizard view for editing maps."""

    def __init__(self, map_data: MapModel, is_mod: bool) -> None:
        """Initialize the wizard view.

        Args:
            map_data: The map being edited.
            is_mod: Whether the user is a moderator.
        """
        super().__init__()
        self.state = MapEditWizardState(map_data, is_mod)
        self.submitted = False
        self.cancelled = False
        self.map_name_page = 0  # Track current page for map name pagination
        self.rebuild()

    def rebuild(self) -> None:  # noqa: PLR0912, PLR0915
        """Rebuild the view based on current state."""
        self.clear_items()

        state = self.state
        step = state.current_step

        # Build container based on step
        container = ui.Container()

        if step == "select_fields":
            container.add_item(
                ui.TextDisplay(
                    f"# Edit Map: {state.map_data.code}\n"
                    f"**{state.map_data.map_name}** by {state.map_data.primary_creator_name}\n\n"
                    "Select which fields you want to edit:"
                )
            )
            container.add_item(ui.Separator())
            container.add_item(ui.ActionRow(FieldSelectionSelect(state.map_data, is_mod=state.is_mod)))
            container.add_item(ui.ActionRow(CancelButton()))

        elif step == "edit_field":
            field = state.current_field
            if field is None:
                # Shouldn't happen, but handle gracefully
                state.current_step = "reason" if not state.is_mod else "review"
                self.rebuild()
                return

            current_value = state.get_pending_value(field)
            progress = f"({state.current_field_index + 1}/{len(state.selected_fields)})"

            container.add_item(
                ui.TextDisplay(
                    f"# Editing: {field.display_name} {progress}\n"
                    f"**Current value:** {self._format_value(current_value)}"
                )
            )
            container.add_item(ui.Separator())

            # Add appropriate editor based on field type
            if field == EditableField.DIFFICULTY:
                container.add_item(ui.ActionRow(DifficultySelect(cast(DifficultyAll | None, current_value))))
            elif field == EditableField.CATEGORY:
                container.add_item(ui.ActionRow(CategorySelect(cast(MapCategory | None, current_value))))
            elif field == EditableField.MAP_NAME:
                # Paginated map name select
                map_select = MapNameSelect(
                    cast(OverwatchMap | None, current_value),
                    page=self.map_name_page,
                )
                container.add_item(ui.ActionRow(map_select))
                # Add pagination buttons
                prev_disabled = self.map_name_page <= 0
                next_disabled = self.map_name_page >= map_select.total_pages - 1
                container.add_item(
                    ui.ActionRow(
                        MapNamePageButton("prev", disabled=prev_disabled),
                        MapNamePageButton("next", disabled=next_disabled),
                    )
                )
            elif field == EditableField.MECHANICS:
                mechanics_value = cast(list[Mechanics] | None, current_value)
                container.add_item(ui.ActionRow(MechanicsSelect(mechanics_value or [])))
            elif field == EditableField.RESTRICTIONS:
                restrictions_value = cast(list[Restrictions] | None, current_value)
                container.add_item(ui.ActionRow(RestrictionsSelect(restrictions_value or [])))
            elif field == EditableField.TAGS:
                tags_value = cast(list[Tags] | None, current_value)
                container.add_item(ui.ActionRow(TagsSelect(tags_value or [])))
            elif field == EditableField.SEND_TO_PLAYTEST:
                current_playtest = cast(
                    DifficultyAll | None,
                    state.get_mod_action(EditableField.SEND_TO_PLAYTEST),
                )
                container.add_item(ui.ActionRow(PlaytestDifficultySelect(current_playtest)))
            elif field == EditableField.OVERRIDE_RATING:
                current_rating = cast(int | None, state.get_mod_action(EditableField.OVERRIDE_RATING))
                container.add_item(ui.ActionRow(RatingOverrideSelect(current_rating)))
            elif field == EditableField.MAKE_LEGACY:
                current_legacy = bool(state.get_mod_action(EditableField.MAKE_LEGACY) or False)
                container.add_item(ui.ActionRow(ModBooleanToggleButton(field, current_legacy)))
            elif field.requires_toggle:
                bool_value = cast(bool | None, current_value)
                container.add_item(ui.ActionRow(BooleanToggleButton(field, bool_value or False)))
            elif field.requires_modal or field == EditableField.MEDALS:
                container.add_item(ui.ActionRow(OpenModalButton(field)))

            container.add_item(ui.ActionRow(BackButton(), CancelButton()))

        elif step == "reason":
            container.add_item(
                ui.TextDisplay(
                    "# Provide a Reason\n"
                    "Please explain why these changes should be made.\n"
                    "This helps moderators understand your request."
                )
            )
            container.add_item(ui.Separator())

            if state.reason:
                container.add_item(ui.TextDisplay(f"**Your reason:**\n{state.reason}"))
                container.add_item(ui.ActionRow(EnterReasonButton()))
                container.add_item(ui.ActionRow(BackButton(), SubmitButton(is_mod=False), CancelButton()))
            else:
                container.add_item(ui.ActionRow(EnterReasonButton()))
                container.add_item(ui.ActionRow(BackButton(), CancelButton()))

        elif step == "review":
            container.add_item(ui.TextDisplay(self._build_review_text()))
            container.add_item(ui.Separator())
            container.add_item(
                ui.ActionRow(
                    BackButton(),
                    SubmitButton(is_mod=state.is_mod),
                    CancelButton(),
                )
            )
        container.add_item(ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"# {self._end_time_string}"))
        self.add_item(container)

    @staticmethod
    def _format_value(value: FieldValue) -> str:
        """Format a value for display."""
        if value is None:
            return "*Not set*"
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "*None*"
        if isinstance(value, bool):
            return "Yes" if value else "No"
        if isinstance(value, MedalsResponse):
            return f"🥇 {value.gold} | 🥈 {value.silver} | 🥉 {value.bronze}"
        return str(value)

    def _build_review_text(self) -> str:
        """Build the review summary text."""
        state = self.state
        lines = [
            f"# Review Changes: {state.map_data.code}",
            "",
        ]

        if state.pending_changes:
            for field_name, new_value in state.pending_changes.items():
                field = EditableField(field_name)
                old_value = state.get_current_value(field)
                lines.append(f"**{field.display_name}:**")
                lines.append(f"  ~~{self._format_value(old_value)}~~ → {self._format_value(new_value)}")
                lines.append("")

        # Mod-only actions review
        if state.is_mod and state.mod_actions:
            playtest = cast(DifficultyAll | None, state.get_mod_action(EditableField.SEND_TO_PLAYTEST))
            if playtest is not None:
                lines.append("**Send to playtest:**")
                lines.append(f"  Difficulty → {playtest}")
                lines.append("")
            make_legacy = bool(state.get_mod_action(EditableField.MAKE_LEGACY) or False)
            if make_legacy:
                lines.append("**Convert to legacy:**")
                lines.append("  No → Yes")
                lines.append("")
            rating = cast(int | None, state.get_mod_action(EditableField.OVERRIDE_RATING))
            if rating is not None:
                lines.append("**Override rating:**")
                lines.append(f"  → {stars_rating_string(rating)} ({rating})")
                lines.append("")

        if state.reason and not state.is_mod:
            lines.append(f"**Reason:** {state.reason}")

        return "\n".join(lines)


class _MapEditVerificationButton(ui.Button["MapEditVerificationView"]):
    view: MapEditVerificationView

    def disable_buttons(self) -> None:
        for item in self.view.walk_children():
            if isinstance(item, ui.Button):
                item.disabled = True


class MapEditAcceptButton(_MapEditVerificationButton):
    """Accept the edit request."""

    def __init__(self) -> None:
        """Initialize the accept button."""
        super().__init__(label="Accept", style=ButtonStyle.green, custom_id="map_edit:accept")

    async def callback(self, itx: GenjiItx) -> None:
        """Handle accept button click to approve the edit request."""
        await itx.response.defer(ephemeral=True, thinking=True)

        data = MapEditResolveRequest(
            accepted=True,
            resolved_by=itx.user.id,
        )

        self.disable_buttons()
        if itx.message:
            await itx.message.edit(view=self.view)

        await itx.client.api.resolve_map_edit_request(self.view.edit_id, data)

        await itx.edit_original_response(content="✅ Edit request accepted and changes applied!")


class MapEditAcceptAndPlaytestButton(_MapEditVerificationButton):
    """Accept the edit request and send to playtest."""

    view: MapEditVerificationView

    def __init__(self) -> None:
        """Initialize the accept and playtest button."""
        super().__init__(
            label="Accept & Send to Playtest",
            style=ButtonStyle.blurple,
            custom_id="map_edit:accept_playtest",
        )

    async def callback(self, itx: GenjiItx) -> None:
        """Handle accept and playtest button click to approve and send to playtest."""
        await itx.response.defer(ephemeral=True, thinking=True)

        data = MapEditResolveRequest(
            accepted=True,
            resolved_by=itx.user.id,
            send_to_playtest=True,
        )

        self.disable_buttons()
        if itx.message:
            await itx.message.edit(view=self.view)

        await itx.client.api.resolve_map_edit_request(self.view.edit_id, data)

        await itx.edit_original_response(content="✅ Edit request accepted, changes applied, and map sent to playtest!")


class MapEditRejectButton(_MapEditVerificationButton):
    """Reject the edit request."""

    view: MapEditVerificationView

    def __init__(self) -> None:
        """Initialize the reject button."""
        super().__init__(label="Reject", style=ButtonStyle.red, custom_id="map_edit:reject")

    async def callback(self, itx: GenjiItx) -> None:
        """Handle reject button click to deny the edit request."""
        # Open modal for rejection reason
        modal = ReasonModal()
        modal.reason_input.label = "Rejection Reason"
        modal.reason_input.placeholder = "Explain why this edit was rejected..."
        await itx.response.send_modal(modal)
        await modal.wait()

        if not modal.submitted_reason:
            return

        data = MapEditResolveRequest(
            accepted=False,
            resolved_by=itx.user.id,
            rejection_reason=modal.submitted_reason,
        )

        self.disable_buttons()

        if itx.message:
            await itx.message.edit(view=self.view)

        await itx.client.api.resolve_map_edit_request(self.view.edit_id, data)

        await itx.followup.send("❌ Edit request rejected.", ephemeral=True)


class MapEditVerificationView(ui.LayoutView):
    """View shown in the verification queue for map edit requests."""

    def __init__(self, data: MapEditSubmissionResponse, original_map_data: MapModel) -> None:
        """Initialize the verification view.

        Args:
            data: The edit request submission data.
            original_map_data: The original map data before the edit.
        """
        super().__init__(timeout=None)
        self.data = data
        self.original_map_data = original_map_data
        self.edit_id = data.id
        self.rebuild_components()

    def _has_difficulty_change(self) -> bool:
        """Check if the edit request includes a difficulty change."""
        return any(change.field == "Difficulty" for change in self.data.changes)

    def rebuild_components(self) -> None:
        """Build the verification view."""
        self.clear_items()

        changes_text = "\n".join(f"**{c.field}:** ~~{c.old_value}~~ → {c.new_value}" for c in self.data.changes)

        action_buttons: list[ui.Item] = [MapEditAcceptButton()]
        if self._has_difficulty_change():
            action_buttons.append(MapEditAcceptAndPlaytestButton())
        action_buttons.append(MapEditRejectButton())

        map_details = FilteredFormatter(self.original_map_data).format()

        creator_ids = [c.id for c in self.original_map_data.creators]
        non_creator_alert = (
            ":warning: **This was submitted by a non-creator.**" if self.data.submitter_id not in creator_ids else ""
        )

        container = ui.Container(
            ui.TextDisplay(f"# Map Edit Request\n**Current Map Data:**\n{map_details}"),
            ui.Separator(),
            ui.TextDisplay(f"**Submitted by:** {self.data.submitter_name}\n**Reason:** {self.data.reason}\n"),
            ui.Separator(),
            ui.TextDisplay(f"## Proposed Changes\n{changes_text}\n{non_creator_alert}"),
            ui.Separator(),
            ui.ActionRow(*action_buttons),
            accent_color=0x5865F2,
        )
        self.add_item(container)


# === Moderation Record Management Views ===


class TimeChangeModal(ui.Modal):
    """Modal for entering new time and reason for a completion."""

    def __init__(self, current_time: float) -> None:
        """Initialize the time change modal.

        Args:
            current_time: The current completion time.
        """
        super().__init__(title="Change Completion Time")
        self.submitted_time: float | None = None
        self.submitted_reason: str | None = None

        self.time_input = ui.TextInput(
            label="New Time (seconds)",
            default=str(current_time),
            required=True,
            max_length=20,
        )
        self.reason_input = ui.TextInput(
            label="Reason for Change",
            style=TextStyle.paragraph,
            placeholder="Explain why the time is being changed...",
            min_length=10,
            max_length=500,
            required=True,
        )
        self.add_item(self.time_input)
        self.add_item(self.reason_input)

    async def on_submit(self, itx: GenjiItx) -> None:
        """Process the submitted values."""
        await itx.response.defer()
        try:
            self.submitted_time = float(self.time_input.value.strip())
            self.submitted_reason = self.reason_input.value.strip()
        except ValueError:
            raise UserFacingError("Time must be a valid number.")
        self.stop()


class MarkSuspiciousModal(ui.Modal):
    """Modal for marking a completion as suspicious."""

    def __init__(self) -> None:
        """Initialize the mark suspicious modal."""
        super().__init__(title="Mark as Suspicious")
        self.submitted_context: str | None = None
        self.submitted_flag_type: Literal["Cheating", "Scripting"] | None = None

        self.context_input = ui.TextInput(
            label="Context",
            style=TextStyle.paragraph,
            placeholder="Explain why this completion is suspicious...",
            min_length=10,
            max_length=500,
            required=True,
        )
        self.flag_type_input = ui.TextInput(
            label="Flag Type (Cheating or Scripting)",
            default="Cheating",
            required=True,
            max_length=20,
        )
        self.add_item(self.context_input)
        self.add_item(self.flag_type_input)

    async def on_submit(self, itx: GenjiItx) -> None:
        """Process the submitted values."""
        await itx.response.defer()
        self.submitted_context = self.context_input.value.strip()
        flag_value = self.flag_type_input.value.strip()
        if flag_value not in ("Cheating", "Scripting"):
            raise UserFacingError("Flag type must be 'Cheating' or 'Scripting'.")
        self.submitted_flag_type = flag_value  # type: ignore
        self.stop()


class ModRecordButton(ui.Button["ModRecordManagementView"]):
    """Base button for record moderation actions."""

    view: ModRecordManagementView

    def __init__(self, record: CompletionLeaderboardFormattable, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the mod record button.

        Args:
            record: The record this button operates on.
            **kwargs: Additional button parameters.
        """
        super().__init__(**kwargs)
        self.record = record


class ChangeTimeButton(ModRecordButton):
    """Button to change the completion time."""

    def __init__(self, record: CompletionLeaderboardFormattable) -> None:
        """Initialize the change time button."""
        super().__init__(record, label="Change Time", style=ButtonStyle.blurple)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle time change."""
        if self.record.id is None:
            raise UserFacingError("Cannot moderate this record: missing ID")

        modal = TimeChangeModal(self.record.time)
        await itx.response.send_modal(modal)
        await modal.wait()

        if not modal.submitted_time or not modal.submitted_reason:
            return

        data = CompletionModerateRequest(
            moderated_by=itx.user.id,
            time=modal.submitted_time,
            time_change_reason=modal.submitted_reason,
        )

        await itx.client.api.moderate_completion(self.record.id, data)
        await itx.followup.send(
            f"✅ Time changed from {self.record.time}s to {modal.submitted_time}s for "
            f"{self.record.name}'s run on {self.record.code}.",
            ephemeral=True,
        )

        # Refresh the view
        await self.view.refresh_records(itx)


class VerifyButton(ModRecordButton):
    """Button to verify a completion."""

    def __init__(self, record: CompletionLeaderboardFormattable) -> None:
        """Initialize the verify button."""
        super().__init__(record, label="Verify", style=ButtonStyle.green)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle verification."""
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.record.id is None:
            raise UserFacingError("Cannot moderate this record: missing ID")

        data = CompletionModerateRequest(
            moderated_by=itx.user.id,
            verified=True,
        )

        await itx.client.api.moderate_completion(self.record.id, data)
        await itx.edit_original_response(
            content=f"✅ Verified {self.record.name}'s run on {self.record.code}.",
        )

        # Refresh the view
        await self.view.refresh_records(itx)


class UnverifyButton(ModRecordButton):
    """Button to unverify a completion."""

    def __init__(self, record: CompletionLeaderboardFormattable) -> None:
        """Initialize the unverify button."""
        super().__init__(record, label="Unverify", style=ButtonStyle.red)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle unverification."""
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.record.id is None:
            raise UserFacingError("Cannot moderate this record: missing ID")

        data = CompletionModerateRequest(
            moderated_by=itx.user.id,
            verified=False,
        )

        await itx.client.api.moderate_completion(self.record.id, data)
        await itx.edit_original_response(
            content=f"❌ Unverified {self.record.name}'s run on {self.record.code}.",
        )

        # Refresh the view
        await self.view.refresh_records(itx)


class MarkSuspiciousButton(ModRecordButton):
    """Button to mark a completion as suspicious."""

    def __init__(self, record: CompletionLeaderboardFormattable) -> None:
        """Initialize the mark suspicious button."""
        super().__init__(record, label="Mark Suspicious", style=ButtonStyle.red)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle marking as suspicious."""
        if self.record.id is None:
            raise UserFacingError("Cannot moderate this record: missing ID")

        modal = MarkSuspiciousModal()
        await itx.response.send_modal(modal)
        await modal.wait()

        if not modal.submitted_context or not modal.submitted_flag_type:
            return

        data = CompletionModerateRequest(
            moderated_by=itx.user.id,
            mark_suspicious=True,
            suspicious_context=modal.submitted_context,
            suspicious_flag_type=modal.submitted_flag_type,
        )

        await itx.client.api.moderate_completion(self.record.id, data)
        await itx.followup.send(
            f"⚠️ Marked {self.record.name}'s run on {self.record.code} as suspicious ({modal.submitted_flag_type}).",
            ephemeral=True,
        )

        # Refresh the view
        await self.view.refresh_records(itx)


class UnmarkSuspiciousButton(ModRecordButton):
    """Button to unmark a completion as suspicious."""

    def __init__(self, record: CompletionLeaderboardFormattable) -> None:
        """Initialize the unmark suspicious button."""
        super().__init__(record, label="Unmark Suspicious", style=ButtonStyle.green)

    async def callback(self, itx: GenjiItx) -> None:
        """Handle unmarking as suspicious."""
        await itx.response.defer(ephemeral=True, thinking=True)
        if self.record.id is None:
            raise UserFacingError("Cannot moderate this record: missing ID")

        data = CompletionModerateRequest(
            moderated_by=itx.user.id,
            unmark_suspicious=True,
        )

        await itx.client.api.moderate_completion(self.record.id, data)
        await itx.edit_original_response(
            content=f"✅ Unmarked {self.record.name}'s run on {self.record.code} as suspicious.",
        )

        # Refresh the view
        await self.view.refresh_records(itx)


class ModRecordManagementView(PaginatorView[CompletionLeaderboardFormattable]):
    """View for managing completion records with moderation actions."""

    def __init__(
        self,
        records: list[CompletionLeaderboardFormattable],
        code_filter: str | None,
        user_filter: int | None,
        verification_filter: Literal["Verified", "Unverified", "All"],
        latest_only: bool,
    ) -> None:
        """Initialize the record management view.

        Args:
            records: List of completion records.
            code_filter: Optional map code filter.
            user_filter: Optional user ID filter.
            verification_filter: Verification status filter.
            latest_only: Whether showing only latest records.
        """
        self.code_filter = code_filter
        self.user_filter = user_filter
        self.verification_filter: Literal["Verified", "Unverified", "All"] = verification_filter
        self.latest_only = latest_only
        super().__init__("Record Management", records, page_size=5)

    async def refresh_records(self, itx: GenjiItx) -> None:
        """Refresh the records from the API and rebuild the view."""
        records = await itx.client.api.get_records_filtered(
            code=self.code_filter,
            user_id=self.user_filter,
            verification_status=self.verification_filter,
            latest_only=self.latest_only,
            page_size=0,  # Fetch all records
            page_number=1,
        )

        if not records:
            await itx.followup.send("No records found after refresh.", ephemeral=True)
            return

        self.rebuild_data(records)
        self.rebuild_components()
        if itx.message:
            await itx.message.edit(view=self)

    def build_page_body(self) -> Sequence[ui.Item]:
        """Build the UI components for the current page of records.

        Returns:
            Sequence[ui.Item]: The list of UI components to display.
        """
        if not self._pages:
            return []

        records = self.current_page
        res = []

        for record in records:
            # Build record info text
            status_emoji = "✅" if record.verified else "❌"
            suspicious_emoji = "⚠️" if record.suspicious else ""
            info_text = (
                f"**Map:** {record.code} - {record.map_name} ({record.difficulty})\n"
                f"**Runner:** {record.name}\n"
                f"**Time:** {record.time}s\n"
                f"**Medal:** {record.medal or 'None'}\n"
                f"**Verified:** {status_emoji}\n"
                f"**Suspicious:** {suspicious_emoji}\n"
                f"**Legacy:** {record.legacy}"
            )

            # Build action buttons for this record
            action_buttons: list[ui.Button] = [ChangeTimeButton(record)]

            if record.verified:
                action_buttons.append(UnverifyButton(record))
            else:
                action_buttons.append(VerifyButton(record))

            if record.suspicious:
                action_buttons.append(UnmarkSuspiciousButton(record))
            else:
                action_buttons.append(MarkSuspiciousButton(record))

            # Add text display and action row for this record
            section = (
                ui.TextDisplay(info_text),
                ui.ActionRow(*action_buttons),
                ui.Separator(),
            )
            res.extend(section)

        return res


class MapEditorService(BaseService):
    """Service for handling map edit events."""

    verification_views: dict[int, MapEditVerificationView] = {}

    async def _resolve_channels(self) -> None:
        """Resolve verification queue channel."""
        channel = self.bot.get_channel(self.bot.config.channels.submission.verification_queue)
        assert isinstance(channel, discord.TextChannel)
        self.verification_channel = channel

    @queue_consumer("api.map_edit.created", struct_type=MapEditCreatedEvent, idempotent=True)
    async def _process_edit_created(self, event: MapEditCreatedEvent, _: AbstractIncomingMessage) -> None:
        """Handle new map edit request - post to verification queue."""
        log.debug(f"[RabbitMQ] Processing map edit created: {event.edit_request_id}")

        # Fetch the full submission data
        data = await self.bot.api.get_map_edit_submission(event.edit_request_id)
        original_map_data = await self.bot.api.get_map(code=data.code)

        # Create and send the verification view
        view = MapEditVerificationView(data, original_map_data)
        message = await self.verification_channel.send(view=view)

        # Store message ID
        await self.bot.api.set_map_edit_message_id(
            event.edit_request_id,
            MapEditSetMessageIdRequest(message_id=message.id),
        )

        self.verification_views[message.id] = view

    @queue_consumer("api.map_edit.resolved", struct_type=MapEditResolvedEvent)
    async def _process_edit_resolved(self, event: MapEditResolvedEvent, _: AbstractIncomingMessage) -> None:
        """Handle resolved map edit - clean up verification queue message.

        Note: User notification is handled by the API via the notification service.
        This consumer only handles Discord-side cleanup (deleting the queue message).
        """
        log.debug(f"[RabbitMQ] Processing map edit resolved: {event.edit_request_id}")

        # Get the edit request details for the message_id
        edit_data = await self.bot.api.get_map_edit_request(event.edit_request_id)

        # Delete verification queue message
        if edit_data.message_id:
            try:
                msg = self.verification_channel.get_partial_message(edit_data.message_id)
                await msg.delete()
            except discord.NotFound:
                pass

            self.verification_views.pop(edit_data.message_id, None)
