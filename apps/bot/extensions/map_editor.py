from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from discord import app_commands
from genjishimada_sdk.maps import OverwatchCode

from extensions.moderator import MapEditVerificationView, MapEditWizardView
from utilities import transformers
from utilities.base import BaseCog
from utilities.errors import UserFacingError

if TYPE_CHECKING:
    from core import Genji
    from utilities._types import GenjiItx


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
                original_map_data = await self.bot.api.get_map(code=data.code)
                view = MapEditVerificationView(data, original_map_data)
                self.bot.add_view(view, message_id=edit.message_id)
                self.bot.map_editor.verification_views[edit.message_id] = view

    @app_commands.command(name="edit-request")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    async def edit_request_non_moderator(
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


async def setup(bot: Genji) -> None:
    """Load the ModeratorCog cog.

    Args:
        bot (Genji): The bot instance.
    """
    await bot.add_cog(MapEditorCog(bot))


async def teardown(bot: Genji) -> None:
    """Unload the ModeratorCog cog.

    Args:
        bot (Genji): The bot instance.
    """
    await bot.remove_cog("MapEditorCog")
