"""Authentication-related event payloads and listeners."""

from __future__ import annotations

import logging
import os

import httpx
from genjishimada_sdk.auth import PasswordResetEmailEvent, VerificationEmailEvent
from litestar.events import listener

log = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SITE_URL = os.getenv("SITE_URL", "https://genji.pk")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@notifications.genji.pk")


async def _send_email_via_resend(to: str, subject: str, html: str) -> bool:
    """Send an email using Resend API."""
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not configured, skipping email send")
        return False

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            response.raise_for_status()
            log.info("Email sent successfully to %s", to)
            return True
        except Exception as exc:
            log.error("Failed to send email to %s: %s", to, exc)
            return False


@listener("auth.verification.requested")
async def send_verification_email(event: VerificationEmailEvent) -> None:
    """Send verification email on registration."""
    verification_url = f"{SITE_URL}/verify-email?token={event.token}"
    html = f"""
    <h1>Welcome to Genji Parkour!</h1>
    <p>Hi {event.username},</p>
    <p>Thank you for registering. Please verify your email address by clicking the link below:</p>
    <p><a href="{verification_url}">Verify Email</a></p>
    <p>This link will expire in 24 hours.</p>
    """
    await _send_email_via_resend(event.email, "Verify your email", html)


@listener("auth.verification.resend")
async def resend_verification_email(event: VerificationEmailEvent) -> None:
    """Resend verification email."""
    verification_url = f"{SITE_URL}/verify-email?token={event.token}"
    html = f"""
    <h1>Verify Your Email</h1>
    <p>Hi {event.username},</p>
    <p>Please verify your email address by clicking the link below:</p>
    <p><a href="{verification_url}">Verify Email</a></p>
    <p>This link will expire in 24 hours.</p>
    """
    await _send_email_via_resend(event.email, "Verify your email", html)


@listener("auth.password_reset.requested")
async def send_password_reset_email(event: PasswordResetEmailEvent) -> None:
    """Send password reset email."""
    reset_url = f"{SITE_URL}/reset-password?token={event.token}"
    html = f"""
    <h1>Reset Your Password</h1>
    <p>Hi {event.username},</p>
    <p>You requested to reset your password. Click the link below to continue:</p>
    <p><a href="{reset_url}">Reset Password</a></p>
    <p>This link will expire in 1 hour.</p>
    <p>If you didn't request this, please ignore this email.</p>
    """
    await _send_email_via_resend(event.email, "Reset your password", html)
