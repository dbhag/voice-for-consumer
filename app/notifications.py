"""Async completion notification — CLAUDE.md's Stack table lists "SMS
(Twilio) or email" as bought infra, independent of the voice-pipeline
concern (unlike Twilio-for-telephony, sending a plain email is generic,
vendor-neutral infra, not the multi-vendor evaluation deferred for
VoicePlatformProvider). Email via stdlib smtplib needs no new dependency.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings


class NotificationProvider(Protocol):
    async def send(self, to: str, subject: str, body: str) -> None: ...


class MockNotificationProvider:
    """Records sends in memory — used by tests, the CLI, and the
    fakeredis-backed demo. Never touches the network.
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


class EmailNotificationProvider:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        from_address: str,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_address = from_address
        self.username = username
        self.password = password

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.smtp_host, self.smtp_port) as smtp:
            smtp.starttls()
            if self.username and self.password:
                smtp.login(self.username, self.password)
            smtp.sendmail(self.from_address, [to], message.as_string())


def build_notification_provider(settings: Settings) -> NotificationProvider:
    if settings.notification_provider == "email":
        if not settings.smtp_host or not settings.smtp_from_address:
            raise ValueError(
                "notification_provider=email requires smtp_host and smtp_from_address"
            )
        return EmailNotificationProvider(
            smtp_host=settings.smtp_host,
            smtp_port=settings.smtp_port,
            from_address=settings.smtp_from_address,
            username=settings.smtp_username,
            password=settings.smtp_password,
        )
    return MockNotificationProvider()
