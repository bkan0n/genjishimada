# apps/bot/extensions/map_editor.py

"""Map editor extension for wizard-style map editing and verification queue."""

from __future__ import annotations

import asyncio
from enum import Enum
from logging import getLogger
from typing import TYPE_CHECKING, Literal, cast, get_args

import discord
from discord import ButtonStyle, SelectOption, TextStyle, app_commands, ui
from genjishimada_sdk.difficulties import DIFFICULTY_RANGES_ALL, DifficultyAll
from genjishimada_sdk.maps import (
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
    Restrictions,
)

from extensions._queue_registry import queue_consumer
from utilities import transformers
from utilities.base import BaseCog, BaseService, BaseView
from utilities.errors import UserFacingError

if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage

    from core import Genji
    from utilities._types import GenjiItx
    from utilities.maps import MapModel

log = getLogger(__name__)


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================


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
    MEDALS = "medals"
    CUSTOM_BANNER = "custom_banner"
    # Mod-only fields (still editable but typically mod-controlled)
    HIDDEN = "hidden"
    ARCHIVED = "archived"
    OFFICIAL = "official"
    CREATORS = "creators"

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
        }


# Preview length for field values in selects
_PREVIEW_MAX_LENGTH = 50

# Static lists for mechanics and restrictions (fetched from SDK Literal types)
# These are the options available in the database


# ============================================================================
# WIZARD STATE
# ============================================================================


# Type alias for field values that can be edited
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


# ============================================================================
# FIELD SELECTION STEP
# ============================================================================


class FieldSelectionSelect(ui.Select["MapEditWizardView"]):
    """Multi-select for choosing which fields to edit."""

    view: MapEditWizardView

    def __init__(self, map_data: MapModel) -> None:
        """Initialize the field selection select.

        Args:
            map_data: The map data to build options from.
        """
        options = [
            SelectOption(
                label=field.display_name,
                value=field.value,
                description=self._get_current_preview(map_data, field),
            )
            for field in EditableField
            if field not in {EditableField.CREATORS}  # Creators handled separately
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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


# ============================================================================
# FIELD EDITING COMPONENTS
# ============================================================================


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

        await itx.response.defer()
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
        gold_str = self.gold_input.value.strip()
        silver_str = self.silver_input.value.strip()
        bronze_str = self.bronze_input.value.strip()

        # If all empty, clear medals
        if not any([gold_str, silver_str, bronze_str]):
            self.submitted_medals = None
            await itx.response.defer()
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
        await itx.response.defer()
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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
        self.view.rebuild()
        await itx.edit_original_response(view=self.view)


# ============================================================================
# REASON INPUT
# ============================================================================


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
            self.view.rebuild()
            await itx.edit_original_response(view=self.view)


# ============================================================================
# NAVIGATION & SUBMISSION
# ============================================================================


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
        await itx.response.edit_message(
            content="Edit cancelled.",
            view=None,
        )


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

        self.view.rebuild()
        await itx.response.edit_message(view=self.view)


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
            # Direct apply
            patch = self._build_patch_request(state)
            await itx.client.api.edit_map(state.map_data.code, patch)
            await itx.edit_original_response(
                content=f"✅ Changes applied to **{state.map_data.code}**!",
                view=None,
            )
        else:
            # Submit for approval
            request = self._build_edit_request(state, itx.user.id)
            await itx.client.api.create_map_edit_request(request)
            await itx.edit_original_response(
                content=(
                    f"✅ Edit request submitted for **{state.map_data.code}**!\nA moderator will review your changes."
                ),
                view=None,
            )

        self.view.submitted = True
        self.view.stop()

    def _build_patch_request(self, state: MapEditWizardState) -> MapPatchRequest:
        """Build a MapPatchRequest from pending changes."""
        kwargs = {}
        for field_name, value in state.pending_changes.items():
            if field_name == "code":
                kwargs["code"] = value
            else:
                kwargs[field_name] = value
        return MapPatchRequest(**kwargs)

    def _build_edit_request(self, state: MapEditWizardState, user_id: int) -> MapEditCreateRequest:
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


# ============================================================================
# MAIN WIZARD VIEW
# ============================================================================


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
        self.rebuild()

    def rebuild(self) -> None:  # noqa: PLR0912
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
            container.add_item(ui.ActionRow(FieldSelectionSelect(state.map_data)))
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
            elif field == EditableField.MECHANICS:
                mechanics_value = cast(list[Mechanics] | None, current_value)
                container.add_item(ui.ActionRow(MechanicsSelect(mechanics_value or [])))
            elif field == EditableField.RESTRICTIONS:
                restrictions_value = cast(list[Restrictions] | None, current_value)
                container.add_item(ui.ActionRow(RestrictionsSelect(restrictions_value or [])))
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

        self.add_item(container)

    def _format_value(self, value: FieldValue) -> str:
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

        if state.reason and not state.is_mod:
            lines.append(f"**Reason:** {state.reason}")

        return "\n".join(lines)


# ============================================================================
# VERIFICATION QUEUE VIEW
# ============================================================================


class MapEditAcceptButton(ui.Button["MapEditVerificationView"]):
    """Accept the edit request."""

    view: MapEditVerificationView

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
        await itx.client.api.resolve_map_edit_request(self.view.edit_id, data)

        # Disable buttons
        for item in self.view.walk_children():
            if isinstance(item, ui.Button):
                item.disabled = True

        if itx.message:
            await itx.message.edit(view=self.view)

        await itx.edit_original_response(content="✅ Edit request accepted and changes applied!")


class MapEditRejectButton(ui.Button["MapEditVerificationView"]):
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
        await itx.client.api.resolve_map_edit_request(self.view.edit_id, data)

        # Disable buttons
        for item in self.view.walk_children():
            if isinstance(item, ui.Button):
                item.disabled = True

        if itx.message:
            await itx.message.edit(view=self.view)

        await itx.followup.send("❌ Edit request rejected.", ephemeral=True)


class MapEditVerificationView(ui.LayoutView):
    """View shown in the verification queue for map edit requests."""

    def __init__(self, data: MapEditSubmissionResponse) -> None:
        """Initialize the verification view.

        Args:
            data: The edit request submission data.
        """
        super().__init__(timeout=None)
        self.data = data
        self.edit_id = data.id
        self.rebuild_components()

    def rebuild_components(self) -> None:
        """Build the verification view."""
        self.clear_items()

        # Build changes display
        changes_text = "\n".join(f"**{c.field}:** ~~{c.old_value}~~ → {c.new_value}" for c in self.data.changes)

        container = ui.Container(
            ui.TextDisplay(
                f"# Map Edit Request\n"
                f"**Map:** {self.data.code} ({self.data.map_name})\n"
                f"**Submitted by:** {self.data.submitter_name}\n"
                f"**Reason:** {self.data.reason}\n"
            ),
            ui.Separator(),
            ui.TextDisplay(f"## Proposed Changes\n{changes_text}"),
            ui.Separator(),
            ui.ActionRow(MapEditAcceptButton(), MapEditRejectButton()),
            accent_color=0x5865F2,  # Discord blurple
        )
        self.add_item(container)


# ============================================================================
# SERVICE
# ============================================================================


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

        # Create and send the verification view
        view = MapEditVerificationView(data)
        message = await self.verification_channel.send(view=view)

        # Store message ID
        await self.bot.api.set_map_edit_message_id(
            event.edit_request_id,
            MapEditSetMessageIdRequest(message_id=message.id),
        )

        self.verification_views[message.id] = view

    @queue_consumer("api.map_edit.resolved", struct_type=MapEditResolvedEvent)
    async def _process_edit_resolved(self, event: MapEditResolvedEvent, _: AbstractIncomingMessage) -> None:
        """Handle resolved map edit - notify submitter and cleanup."""
        log.debug(f"[RabbitMQ] Processing map edit resolved: {event.edit_request_id}")

        # Get the edit request details
        edit_data = await self.bot.api.get_map_edit_request(event.edit_request_id)

        # Notify the submitter
        if event.accepted:
            message = (
                f"✅ Your edit request for **{edit_data.code}** has been **approved**!\n"
                "Your changes have been applied to the map."
            )
        else:
            message = (
                f"❌ Your edit request for **{edit_data.code}** has been **rejected**.\n"
                f"**Reason:** {event.rejection_reason}"
            )

        # Send DM notification directly since we don't have a dedicated notification type
        try:
            user = self.bot.get_user(edit_data.created_by)
            if user is None:
                user = await self.bot.fetch_user(edit_data.created_by)
            await user.send(message)
        except discord.HTTPException:
            log.warning(f"Failed to send DM to user {edit_data.created_by} for map edit resolution")

        # Delete verification queue message
        if edit_data.message_id:
            try:
                msg = self.verification_channel.get_partial_message(edit_data.message_id)
                await msg.delete()
            except discord.NotFound:
                pass

            self.verification_views.pop(edit_data.message_id, None)


# ============================================================================
# COG
# ============================================================================


class MapEditorCog(BaseCog):
    """Commands for editing maps."""

    _startup_task: asyncio.Task

    async def cog_load(self) -> None:
        """Load pending verification views on startup."""
        self._startup_task = asyncio.create_task(self._restore_views())

    async def _restore_views(self) -> None:
        """Restore persistent views for pending edit requests."""
        await self.bot.rabbit.wait_until_drained()

        pending = await self.bot.api.get_pending_map_edit_requests()
        for edit in pending:
            if edit.message_id:
                data = await self.bot.api.get_map_edit_submission(edit.id)
                view = MapEditVerificationView(data)
                self.bot.add_view(view, message_id=edit.message_id)
                self.bot.map_editor.verification_views[edit.message_id] = view

    @app_commands.command(name="suggest-edit")
    async def suggest_edit(
        self,
        itx: GenjiItx,
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer],
    ) -> None:
        """Suggest changes to a map for moderator approval.

        Args:
            itx: The interaction context.
            code: The map code to edit.
        """
        await itx.response.defer(ephemeral=True)

        # Fetch map data
        map_data = await itx.client.api.get_map(code=code)
        if not map_data:
            raise UserFacingError(f"Map `{code}` not found.")

        # Start wizard - for this command, always queue (user path)
        view = MapEditWizardView(map_data, is_mod=False)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @app_commands.command(name="edit-map")
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


# ============================================================================
# SETUP
# ============================================================================


async def setup(bot: Genji) -> None:
    """Load the MapEditorCog."""
    bot.map_editor = MapEditorService(bot)
    await bot.add_cog(MapEditorCog(bot))


async def teardown(bot: Genji) -> None:
    """Unload the MapEditorCog."""
    await bot.remove_cog("MapEditorCog")
