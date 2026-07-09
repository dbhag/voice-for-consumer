from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config import Settings
from app.notifications import (
    EmailNotificationProvider,
    MockNotificationProvider,
    build_notification_provider,
)


async def test_mock_provider_records_sends_without_touching_the_network() -> None:
    provider = MockNotificationProvider()

    await provider.send("user@example.com", "Your quote is ready", "3 of 4 shops responded.")

    assert provider.sent == [
        ("user@example.com", "Your quote is ready", "3 of 4 shops responded.")
    ]


async def test_email_provider_sends_via_smtp_with_starttls_and_login() -> None:
    provider = EmailNotificationProvider(
        smtp_host="smtp.example.com",
        smtp_port=587,
        from_address="proxy@example.com",
        username="proxy",
        password="secret",
    )
    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    with patch("smtplib.SMTP", return_value=mock_smtp_instance) as mock_smtp_cls:
        await provider.send("user@example.com", "Your quote is ready", "body text")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 587)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with("proxy", "secret")
    from_addr, to_addrs, message_text = mock_smtp_instance.sendmail.call_args.args
    assert from_addr == "proxy@example.com"
    assert to_addrs == ["user@example.com"]
    assert "Your quote is ready" in message_text
    assert "body text" in message_text


async def test_email_provider_skips_login_when_no_credentials() -> None:
    provider = EmailNotificationProvider(
        smtp_host="smtp.example.com", smtp_port=587, from_address="proxy@example.com"
    )
    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance

    with patch("smtplib.SMTP", return_value=mock_smtp_instance):
        await provider.send("user@example.com", "subject", "body")

    mock_smtp_instance.login.assert_not_called()


def test_build_notification_provider_defaults_to_mock() -> None:
    provider = build_notification_provider(Settings())
    assert isinstance(provider, MockNotificationProvider)


def test_build_notification_provider_email_requires_host_and_from_address() -> None:
    settings = Settings(notification_provider="email")
    with pytest.raises(ValueError, match="smtp_host"):
        build_notification_provider(settings)


def test_build_notification_provider_builds_email_provider_when_configured() -> None:
    settings = Settings(
        notification_provider="email",
        smtp_host="smtp.example.com",
        smtp_from_address="proxy@example.com",
    )
    provider = build_notification_provider(settings)
    assert isinstance(provider, EmailNotificationProvider)
