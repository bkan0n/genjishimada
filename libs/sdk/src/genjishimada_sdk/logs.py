import datetime as dt
from typing import Literal

from msgspec import Struct

from .maps import OverwatchCode

__all__ = (
    "LogCreateRequest",
    "MapClickCreateRequest",
)


class LogCreateRequest(Struct):
    """Payload for recording a command usage log entry.

    Attributes:
        command_name: Name of the executed command.
        user_id: Identifier of the user who ran the command.
        created_at: Timestamp when the command was executed.
        namespace: Arbitrary namespace metadata to store with the log.
    """

    command_name: str
    user_id: int
    created_at: dt.datetime
    namespace: dict


class MapClickCreateRequest(Struct):
    """Payload for recording a click on a map banner or link.

    Attributes:
        code: Workshop code for the clicked map.
        ip_address: IP address of the user who clicked.
        user_id: Optional identifier of the clicking user.
        source: Origin of the click, such as web or bot.
    """

    code: OverwatchCode
    ip_address: str
    user_id: int | None
    source: Literal["web", "bot"] = "web"
