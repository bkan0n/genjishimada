import logging
import os

import aiohttp
import discord
from discord.ext import commands

import extensions
import utilities.config
from extensions.api_service import APIService
from extensions.completions import CompletionHandler
from extensions.moderator import MapEditHandler
from extensions.newsfeed import NewsfeedHandler
from extensions.notifications import NotificationHandler
from extensions.playtest import PlaytestHandler
from extensions.rabbit import RabbitHandler
from extensions.video_thumbnail import VideoThumbnailHandler
from extensions.xp import XPHandler

__all__ = ("Genji",)


log = logging.getLogger(__name__)

intents = discord.Intents(
    guild_messages=True,
    guilds=True,
    integrations=True,
    dm_messages=True,
    webhooks=True,
    members=True,
    message_content=True,
    guild_reactions=True,
)


class Genji(commands.Bot):
    _notification_service: NotificationHandler
    _rabbit_client: RabbitHandler
    _playtest_manager: PlaytestHandler
    _newsfeed_client: NewsfeedHandler
    _api_service: APIService
    _completions_manager: CompletionHandler
    _xp_manager: XPHandler
    _thumbnail_service: VideoThumbnailHandler
    _map_editor_service: MapEditHandler

    def __init__(self, *, prefix: str, session: aiohttp.ClientSession) -> None:
        """Initialize Bot instance.

        Args:
            prefix: The command prefix for the bot.
            session: The aiohttp.ClientSession instance.
        """
        super().__init__(
            command_prefix=prefix,
            intents=intents,
            help_command=None,
            description="Genji Shimada, a Discord bot for the Genji Parkour community.",
        )
        self.session = session
        config = "prod" if os.getenv("APP_ENVIRONMENT") == "production" else "dev"
        with open(f"configs/{config}.toml", "rb") as f:
            self.config = utilities.config.decode(f.read())

    async def on_ready(self) -> None:
        """Log when the bot is ready."""
        log.info(f"Logged in as {self.user}")

    async def setup_hook(self) -> None:
        """Execute code during the initial setup."""
        for ext in ["jishaku", *extensions.EXTENSIONS]:
            log.info(f"Loading {ext}...")
            await self.load_extension(ext)
        log.debug("[Genji.setup_hook] Scheduling rabbit.start()")
        self.loop.call_soon(self.rabbit.start)

    @property
    def notifications(self) -> NotificationHandler:
        """Return the notification service."""
        if self._notification_service is None:
            raise AttributeError("Notification service not initialized.")
        return self._notification_service

    @notifications.setter
    def notifications(self, service: NotificationHandler) -> None:
        self._notification_service = service

    @property
    def rabbit(self) -> RabbitHandler:
        """Return the notification service."""
        if self._rabbit_client is None:
            raise AttributeError("Notification service not initialized.")
        return self._rabbit_client

    @rabbit.setter
    def rabbit(self, service: RabbitHandler) -> None:
        self._rabbit_client = service

    @property
    def playtest(self) -> PlaytestHandler:
        """Return the playtest service."""
        if self._playtest_manager is None:
            raise AttributeError("Playtest service not initialized.")
        return self._playtest_manager

    @playtest.setter
    def playtest(self, service: PlaytestHandler) -> None:
        self._playtest_manager = service

    @property
    def newsfeed(self) -> NewsfeedHandler:
        """Return the newsfeed service."""
        if self._newsfeed_client is None:
            raise AttributeError("Newsfeed service not initialized.")
        return self._newsfeed_client

    @newsfeed.setter
    def newsfeed(self, service: NewsfeedHandler) -> None:
        self._newsfeed_client = service

    @property
    def api(self) -> APIService:
        """Return the API client."""
        return self._api_service

    @api.setter
    def api(self, service: APIService) -> None:
        self._api_service = service

    @property
    def completions(self) -> CompletionHandler:
        """Return the CompletionHandler service."""
        return self._completions_manager

    @completions.setter
    def completions(self, service: CompletionHandler) -> None:
        self._completions_manager = service

    @property
    def xp(self) -> XPHandler:
        """Return the CompletionHandler service."""
        return self._xp_manager

    @xp.setter
    def xp(self, service: XPHandler) -> None:
        self._xp_manager = service

    @property
    def thumbnail_service(self) -> VideoThumbnailHandler:
        """Return the VideoThumbnailHandler."""
        return self._thumbnail_service

    @thumbnail_service.setter
    def thumbnail_service(self, service: VideoThumbnailHandler) -> None:
        self._thumbnail_service = service

    @property
    def map_editor(self) -> MapEditHandler:
        """Return the MapEditHandler."""
        return self._map_editor_service

    @map_editor.setter
    def map_editor(self, service: MapEditHandler) -> None:
        self._map_editor_service = service
