from __future__ import annotations

import os
import typing
from logging import getLogger

from discord import ButtonStyle, TextStyle, app_commands, ui
from genjishimada_sdk.notifications import (
    NotificationChannel,
    NotificationEventType,
    NotificationPreferencesResponse,
)
from genjishimada_sdk.users import (
    OverwatchUsernameItem,
    OverwatchUsernamesResponse,
    OverwatchUsernamesUpdateRequest,
)

from utilities.base import BaseCog, BaseView

if typing.TYPE_CHECKING:
    from core.genji import Genji
    from utilities._types import GenjiItx

log = getLogger(__name__)


def bool_string(value: bool) -> str:
    """Return ON or OFF depending on the boolean value given."""
    return "ON" if value else "OFF"


ENABLED_EMOJI = "🔔"
DISABLED_EMOJI = "🔕"


# Mapping from UI labels to (event_type, channel) pairs
# This defines what each toggle in the settings UI controls
NOTIFICATION_SETTINGS = {
    # DM notifications
    "dm_on_verification": (NotificationEventType.VERIFICATION_APPROVED, NotificationChannel.DISCORD_DM),
    "dm_on_skill_role_update": (NotificationEventType.SKILL_ROLE_UPDATE, NotificationChannel.DISCORD_DM),
    "dm_on_lootbox_gain": (NotificationEventType.LOOTBOX_EARNED, NotificationChannel.DISCORD_DM),
    "dm_on_records_removal": (NotificationEventType.RECORD_REMOVED, NotificationChannel.DISCORD_DM),
    "dm_on_playtest_alerts": (NotificationEventType.PLAYTEST_UPDATE, NotificationChannel.DISCORD_DM),
    # Channel ping notifications
    "ping_on_xp_gain": (NotificationEventType.XP_GAIN, NotificationChannel.DISCORD_PING),
    "ping_on_mastery": (NotificationEventType.MASTERY_EARNED, NotificationChannel.DISCORD_PING),
    "ping_on_community_rank_update": (NotificationEventType.RANK_UP, NotificationChannel.DISCORD_PING),
}


class SettingsView(BaseView):
    def __init__(
        self,
        preferences: list[NotificationPreferencesResponse],
        current_usernames: OverwatchUsernamesResponse,
    ) -> None:
        """Initialize SettingsView.

        Args:
            preferences: List of notification preferences for the user.
            current_usernames: The usernames a user currently has assigned.
        """
        self.preferences = preferences
        self.current_usernames = current_usernames
        # Build a lookup dict for quick access: (event_type, channel) -> enabled
        self._pref_lookup: dict[tuple[str, str], bool] = {}
        for pref in preferences:
            for channel, enabled in pref.channels.items():
                self._pref_lookup[(pref.event_type, channel)] = enabled
        super().__init__(timeout=360)
        self.rebuild_components()

    def _is_enabled(self, setting_key: str) -> bool:
        """Check if a setting is enabled based on preferences."""
        if setting_key not in NOTIFICATION_SETTINGS:
            return False
        event_type, channel = NOTIFICATION_SETTINGS[setting_key]
        # Default to True if preference not found (matches DEFAULT_CHANNELS behavior)
        return self._pref_lookup.get((event_type.value, channel.value), True)

    def update_pref_lookup(self, setting_key: str, enabled: bool) -> None:
        """Update the local preference lookup after a toggle."""
        if setting_key in NOTIFICATION_SETTINGS:
            event_type, channel = NOTIFICATION_SETTINGS[setting_key]
            self._pref_lookup[(event_type.value, channel.value)] = enabled

    def rebuild_components(self) -> None:
        """Rebuild the necessary components for the view."""
        self.clear_items()

        self._dm_on_verification_button = NotificationButton(
            "dm_on_verification",
            self._is_enabled("dm_on_verification"),
        )
        self._dm_on_skill_role_update_button = NotificationButton(
            "dm_on_skill_role_update",
            self._is_enabled("dm_on_skill_role_update"),
        )
        self._dm_on_lootbox_gain_button = NotificationButton(
            "dm_on_lootbox_gain",
            self._is_enabled("dm_on_lootbox_gain"),
        )
        self._dm_on_records_removal_button = NotificationButton(
            "dm_on_records_removal",
            self._is_enabled("dm_on_records_removal"),
        )
        self._dm_on_playtest_alerts_button = NotificationButton(
            "dm_on_playtest_alerts",
            self._is_enabled("dm_on_playtest_alerts"),
        )
        self._ping_on_xp_gain_button = NotificationButton(
            "ping_on_xp_gain",
            self._is_enabled("ping_on_xp_gain"),
        )
        self._ping_on_mastery_button = NotificationButton(
            "ping_on_mastery",
            self._is_enabled("ping_on_mastery"),
        )
        self._ping_on_community_rank_update_button = NotificationButton(
            "ping_on_community_rank_update",
            self._is_enabled("ping_on_community_rank_update"),
        )

        container = ui.Container(
            ui.TextDisplay("# Settings"),
            ui.Separator(),
            ui.TextDisplay("### Direct Messages"),
            ui.Section(
                ui.TextDisplay("Direct message on completion/records verification."),
                accessory=self._dm_on_verification_button,
            ),
            ui.Section(
                ui.TextDisplay("Direct message on skill role updates."),
                accessory=self._dm_on_skill_role_update_button,
            ),
            ui.Section(
                ui.TextDisplay("Direct message on lootbox gain."),
                accessory=self._dm_on_lootbox_gain_button,
            ),
            ui.Section(
                ui.TextDisplay("Direct message on record/completion removal."),
                accessory=self._dm_on_records_removal_button,
            ),
            ui.Section(
                ui.TextDisplay("Direct message on followed playtest updates."),
                accessory=self._dm_on_playtest_alerts_button,
            ),
            ui.TextDisplay("### Pings"),
            ui.Section(
                ui.TextDisplay("Ping in XP channel when XP gained."),
                accessory=self._ping_on_xp_gain_button,
            ),
            ui.Section(
                ui.TextDisplay("Ping in XP channel when map mastery gained."),
                accessory=self._ping_on_mastery_button,
            ),
            ui.Section(
                ui.TextDisplay("Ping in XP channel when community rank has changed."),
                accessory=self._ping_on_community_rank_update_button,
            ),
            ui.Separator(),
            ui.TextDisplay("# Overwatch Usernames"),
            ui.Section(
                ui.TextDisplay(
                    "Set your Overwatch username and alt accounts (if any). "
                    "This helps speed up the verification process"
                ),
                accessory=OpenOverwatchUsernamesModalButton(self.current_usernames),
            ),
            ui.Separator(),
            ui.TextDisplay(self._end_time_string),
        )
        self.add_item(container)


class NotificationButton(ui.Button["SettingsView"]):
    view: SettingsView

    def __init__(self, setting_key: str, enabled: bool) -> None:
        """Initialize NotificationButton.

        Args:
            setting_key: Key identifying which setting this button controls.
            enabled: Whether the notification is currently enabled.
        """
        super().__init__()
        self.setting_key = setting_key
        self.enabled = enabled
        self._edit_button(enabled)

    async def callback(self, itx: GenjiItx) -> None:
        """Notification button callback."""
        # Toggle the state
        self.enabled = not self.enabled
        self._edit_button(self.enabled)

        # Update local lookup so rebuild works correctly
        self.view.update_pref_lookup(self.setting_key, self.enabled)

        # Update the view
        await itx.response.edit_message(view=self.view)

        # Get the event_type and channel for this setting
        if self.setting_key in NOTIFICATION_SETTINGS:
            event_type, channel = NOTIFICATION_SETTINGS[self.setting_key]
            # Call the new preferences API
            await itx.client.api.update_notification_preference(
                itx.user.id,
                event_type.value,
                channel.value,
                self.enabled,
            )

    def _edit_button(self, enabled: bool) -> None:
        """Edit button appearance based on enabled state."""
        self.label = bool_string(enabled)
        self.emoji = ENABLED_EMOJI if enabled else DISABLED_EMOJI
        self.style = ButtonStyle.green if enabled else ButtonStyle.red


class OpenOverwatchUsernamesModalButton(ui.Button["SettingsView"]):
    view: "SettingsView"

    def __init__(self, current_usernames: OverwatchUsernamesResponse) -> None:
        """Initialize OpenOverwatchUsernamesModalButton.

        Args:
            current_usernames: The usernames a user currently has assigned.
        """
        self.current_usernames = current_usernames
        super().__init__(style=ButtonStyle.green, label="Edit")

    async def callback(self, itx: GenjiItx) -> None:
        """Add Overwatch username button callback."""
        modal = OverwatchUsernameModal(self.current_usernames)
        await itx.response.send_modal(modal)
        await modal.wait()
        if not modal.completed:
            return

        inputs = (modal.primary, modal.secondary, modal.tertiary)
        new_usernames = []
        for i in inputs:
            assert isinstance(i.component, ui.TextInput)
            if i.component.value:
                new_usernames.append(OverwatchUsernameItem(i.component.value, i.text == "Primary Overwatch Username"))
        await itx.client.api.update_overwatch_usernames(itx.user.id, OverwatchUsernamesUpdateRequest(new_usernames))
        self.view.current_usernames = await itx.client.api.get_overwatch_usernames(itx.user.id)
        _view = self.view
        self.view.rebuild_components()
        await itx.edit_original_response(view=_view)


class OverwatchUsernameModal(ui.Modal):
    def __init__(self, current_usernames: OverwatchUsernamesResponse) -> None:
        """Initialize OverwatchUsernameModal.

        Args:
            current_usernames: The usernames a user currently has assigned.
        """
        self.completed = False
        self.current_usernames = current_usernames
        super().__init__(title="Set Overwatch Usernames")
        self.build_components()

    def build_components(self) -> None:
        """Build the necessary components."""
        self.primary = ui.Label(
            text="Primary Overwatch Username",
            component=ui.TextInput(
                style=TextStyle.short,
                placeholder="Enter your primary Overwatch username. The number after your username is not required.",
                default=self.current_usernames.primary,
                max_length=25,
                required=True,
            ),
        )

        self.secondary = ui.Label(
            text="Alt Overwatch Username 1",
            component=ui.TextInput(
                style=TextStyle.short,
                placeholder="Enter an alternate Overwatch username. The number after your username is not required.",
                default=self.current_usernames.secondary,
                max_length=25,
                required=False,
            ),
        )

        self.tertiary = ui.Label(
            text="Alt Overwatch Username 2",
            component=ui.TextInput(
                style=TextStyle.short,
                placeholder="Enter an alternate Overwatch username. The number after your username is not required.",
                default=self.current_usernames.tertiary,
                max_length=25,
                required=False,
            ),
        )
        self.add_item(self.primary)
        self.add_item(self.secondary)
        self.add_item(self.tertiary)

    async def on_submit(self, itx: GenjiItx) -> None:
        """Callback for the modal."""
        self.completed = True
        await itx.response.send_message("Overwatch names have been set.", ephemeral=True)


class SettingsCog(BaseCog):
    @app_commands.command()
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    async def settings(self, itx: GenjiItx) -> None:
        """Change various settings like notifications and your display name."""
        await itx.response.defer(ephemeral=True)
        # Fetch preferences from the new API
        preferences = await self.bot.api.get_notification_preferences(itx.user.id)
        current_usernames = await self.bot.api.get_overwatch_usernames(itx.user.id)
        view = SettingsView(preferences, current_usernames)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx

    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    @app_commands.command(name="rank-card")
    async def rank_card(self, itx: GenjiItx) -> None:
        """View the rank card of a user."""
        await itx.response.send_message(
            "This feature has been permanently moved to our website.\nhttps://genji.pk/rank_card",
            ephemeral=True,
        )


async def setup(bot: Genji) -> None:
    """Add SettingsCog to bot."""
    await bot.add_cog(SettingsCog(bot))
