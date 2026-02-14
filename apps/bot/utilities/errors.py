from __future__ import annotations

import contextlib
import logging
import os
import traceback
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Literal

import discord
import sentry_sdk
from discord import ButtonStyle, HTTPException, NotFound, TextStyle, app_commands, ui

from .base import BaseView

if TYPE_CHECKING:
    from utilities._types import GenjiItx

SENTRY_AUTH_TOKEN = os.getenv("SENTRY_AUTH_TOKEN", "")
SENTRY_FEEDBACK_URL = os.getenv("SENTRY_FEEDBACK_URL", "")

log = logging.getLogger(__name__)


class UserFacingError(app_commands.errors.AppCommandError): ...


class APIUnavailableError(Exception):
    pass


class APIHTTPError(Exception):
    def __init__(  # noqa: PLR0913
        self,
        status: int,
        message: str | None,
        error: str | None,
        extra: dict | None,
        *,
        method: str | None = None,
        route: str | None = None,
        url: str | None = None,
        request_mode: Literal["json", "multipart"] | None = None,
        request_params: dict[str, Any] | None = None,
        request_file_field: str | None = None,
        request_filename: str | None = None,
        request_content_type: str | None = None,
        response_preview: str | None = None,
    ) -> None:
        """Init API Error."""
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message
        self.error = error
        self.extra = extra
        self.method = method
        self.route = route
        self.url = url
        self.request_mode = request_mode
        self.request_params = request_params
        self.request_file_field = request_file_field
        self.request_filename = request_filename
        self.request_content_type = request_content_type
        self.response_preview = response_preview


class ReportIssueModal(ui.Modal):
    feedback = ui.TextInput(
        label="Add more info",
        style=TextStyle.long,
        placeholder="Please include any additional context.\n\nWhat were you doing when this happened?",
    )

    def __init__(self, original_itx: GenjiItx) -> None:
        """Init."""
        self.original_itx = original_itx
        super().__init__(title="Report Issue")

    async def on_submit(self, itx: GenjiItx) -> None:
        """On submit."""
        await itx.response.send_message(
            "Thank you for your feedback. This has been logged :)",
            ephemeral=True,
        )
        await self.original_itx.delete_original_response()


class ReportIssueButton(ui.Button["ErrorView"]):
    view: "ErrorView"

    def __init__(self, *, label: str = "Report Issue", style: ButtonStyle = ButtonStyle.red) -> None:
        """Init."""
        super().__init__(label=label, style=style)

    async def callback(self, itx: GenjiItx) -> None:
        """Callback."""
        modal = ReportIssueModal(original_itx=itx)
        await itx.response.send_modal(modal)
        await modal.wait()

        if modal.feedback.value is not None and self.view.sentry_event_id is not None:
            try:
                data = {
                    "name": f"{self.view.exception_itx.user.name} ({self.view.exception_itx.user.id})",
                    "email": "genjishimada@bkan0n.com",
                    "comments": modal.feedback.value,
                    "event_id": self.view.sentry_event_id,
                }

                log.debug("Submitting feedback to Sentry: %s", SENTRY_FEEDBACK_URL)
                log.debug("Feedback data: %s", data)

                resp = await itx.client.session.post(
                    SENTRY_FEEDBACK_URL,
                    headers={
                        "Authorization": f"Bearer {SENTRY_AUTH_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=data,
                )

                response_text = await resp.text()

                if resp.status >= HTTPStatus.BAD_REQUEST.value:
                    log.error(
                        "Failed to submit Sentry feedback. Status: %s, Response: %s",
                        resp.status,
                        response_text,
                    )
                else:
                    log.info(
                        "Successfully submitted feedback for event %s by user %s",
                        self.view.sentry_event_id,
                        self.view.exception_itx.user.id,
                    )

            except Exception as e:
                log.error("Exception while submitting Sentry feedback: %s", e, exc_info=True)

        self.view.stop()


class ErrorView(BaseView):
    def __init__(
        self,
        sentry_event_id: str | None,
        exc: Exception,
        exception_itx: GenjiItx,
        *,
        unknown_error: bool = False,
        description: str = "None",
    ) -> None:
        """Init."""
        self.sentry_event_id = sentry_event_id
        self.exc = exc
        self.exception_itx = exception_itx
        self.description = description
        self.unknown_error = unknown_error
        self._report_issue_button = ReportIssueButton(
            label="Report Issue" if unknown_error else "Send Feedback",
            style=ButtonStyle.red if unknown_error else ButtonStyle.blurple,
        )
        super().__init__(timeout=180)

    def rebuild_components(self) -> None:
        """Rebuild view components."""
        self.clear_items()
        container = ui.Container(
            ui.Section(
                ui.TextDisplay("## Uh-oh! Something went wrong." if self.unknown_error else "## What happened?"),
                ui.TextDisplay(f">>> Details: {self.description}"),
                accessory=ui.Thumbnail(
                    media="http://bkan0n.com/assets/images/icons/error.png"
                    if self.unknown_error
                    else "https://bkan0n.com/assets/images/icons/warning.png"
                ),
            ),
            ui.Separator(),
            ui.TextDisplay(f"# {self._end_time_string}"),
            ui.Separator(),
            ui.Section(
                ui.TextDisplay(
                    "-# Let us know what led to this and what you expected — your feedback helps us fix it faster!"
                    if self.unknown_error
                    else "-# Think this was a mistake? Let us know what happened and what you were expecting."
                ),
                accessory=self._report_issue_button,
            ),
            accent_color=discord.Color.red() if self.unknown_error else discord.Color.yellow(),
        )
        self.add_item(container)


async def on_command_error(itx: GenjiItx, error: Exception) -> None:  # noqa: PLR0912
    """Handle application command errors."""
    exception = getattr(error, "original", error)
    is_user_facing = False
    description = "Unknown error."
    missing_api_error_text = False

    if isinstance(exception, UserFacingError):
        is_user_facing = True
        description = str(exception)
    elif isinstance(exception, APIHTTPError):
        if HTTPStatus.BAD_REQUEST.value <= exception.status < HTTPStatus.INTERNAL_SERVER_ERROR.value:
            is_user_facing = True
            description = (exception.error or "").strip() or "Error"
            missing_api_error_text = description == "Error"
    elif isinstance(exception, APIUnavailableError):
        is_user_facing = True
        description = "We are having trouble connecting to some backend services. Please try again later."

    # Set user context before capturing the exception
    with sentry_sdk.isolation_scope() as scope:
        scope.set_user(
            {
                "id": str(itx.user.id),
                "username": itx.user.name,
            }
        )
        scope.set_tag("command", itx.command.name if itx.command else "unknown")

        # Tag user-facing errors so they can be filtered out in Sentry.
        if is_user_facing:
            scope.set_tag("user_facing", True)
            scope.set_level("info")

        if isinstance(exception, APIHTTPError):
            scope.set_tag("api_status", str(exception.status))
            if exception.method:
                scope.set_tag("api_method", exception.method)
            if exception.route:
                scope.set_tag("api_route", exception.route)

            scope.set_context(
                "API Error",
                {
                    "status": exception.status,
                    "message": exception.message,
                    "error": exception.error,
                    "extra": exception.extra,
                    "method": exception.method,
                    "route": exception.route,
                    "url": exception.url,
                    "request_mode": exception.request_mode,
                    "request_params": exception.request_params,
                    "request_file_field": exception.request_file_field,
                    "request_filename": exception.request_filename,
                    "request_content_type": exception.request_content_type,
                    "response_preview": exception.response_preview,
                },
            )

            if missing_api_error_text:
                scope.set_tag("api_missing_error_text", True)

        if itx.namespace:
            scope.set_context("Command Args", {"Args": dict(itx.namespace.__dict__.items())})

        # Capture the exception with all the context
        event_id = sentry_sdk.capture_exception(exception)

        if missing_api_error_text:
            sentry_sdk.capture_message("Missing API error text for 4xx response", level="warning")

    view = ErrorView(
        event_id,
        exception,
        itx,
        description=description,
        unknown_error=not is_user_facing,
    )
    view.original_interaction = itx

    log.debug(traceback.format_exception(None, exception, exception.__traceback__))

    with contextlib.suppress(HTTPException, NotFound):
        if itx.response.is_done():
            await itx.edit_original_response(content=None, view=view)  # type: ignore
        else:
            await itx.response.send_message(view=view, ephemeral=True)

    if not is_user_facing:
        raise exception
