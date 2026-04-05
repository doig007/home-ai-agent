"""Shared test fixtures for Gemini Insights."""

from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gemini_insights.const import (
    CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
    CONF_ENABLE_LEARNING,
    CONF_ENTITIES,
    CONF_FORECAST_HOURS,
    CONF_HISTORY_PERIOD,
    CONF_MAX_CONFIRMATION_REQUESTS,
    CONF_NOTIFICATION_SERVICE,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PROMPT,
    DEFAULT_MODEL,
    DOMAIN,
    HISTORY_LATEST_ONLY,
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in tests."""
    yield


@pytest.fixture
def mock_gemini_client():
    """Patch Gemini client creation and return a configurable async mock client."""
    client = type("GeminiClientMock", (), {})()
    client.get_insights = AsyncMock()

    with patch(
        "custom_components.gemini_insights.GeminiClient.async_create",
        AsyncMock(return_value=client),
    ):
        yield client


@pytest.fixture
def config_entry():
    """Build a config entry with learning enabled by default."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Gemini Insights",
        data={
            "api_key": "test-api-key",
            "model": DEFAULT_MODEL,
        },
        options={
            CONF_ENTITIES: ["binary_sensor.kitchen_motion"],
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_UPDATE_INTERVAL: 600,
            CONF_HISTORY_PERIOD: HISTORY_LATEST_ONLY,
            CONF_ENABLE_LEARNING: True,
            CONF_FORECAST_HOURS: 12,
            CONF_ENABLE_CONFIRMATION_NOTIFICATIONS: False,
            CONF_NOTIFICATION_SERVICE: "",
            CONF_MAX_CONFIRMATION_REQUESTS: 1,
        },
    )
