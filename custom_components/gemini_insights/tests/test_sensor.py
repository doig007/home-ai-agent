"""Test the Gemini Insights sensors."""
from unittest.mock import patch, AsyncMock # AsyncMock for async methods

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.setup import async_setup_component
from homeassistant.const import CONF_API_KEY

from custom_components.gemini_insights.const import (
    DOMAIN,
    CONF_ENTITIES,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    CONF_HISTORY_PERIOD,
    HISTORY_LATEST_ONLY,
    HISTORY_24_HOURS,
)
from homeassistant.util import dt as dt_util # For time manipulation in tests
from datetime import timedelta
import json # For checking JSON arguments


# from custom_components.gemini_insights.sensor import GeminiInsightsSensor # Not directly used if testing via state machine

# Use common_config_data from conftest.py
# VALID_CONFIG_DATA = {CONF_API_KEY: "test_api_key_123"}
COMMON_OPTIONS_DATA = {
    CONF_ENTITIES: ["sensor.test_entity1"],
    CONF_PROMPT: "Test prompt: {entity_data}",
    CONF_UPDATE_INTERVAL: 600, # 10 minutes
    CONF_HISTORY_PERIOD: HISTORY_LATEST_ONLY, # Default for most tests
}


async def test_sensor_creation_and_initial_state_latest_only(

    hass: HomeAssistant,
    init_integration, # Fixture from conftest.py
    mock_gemini_client_class, # Fixture from conftest.py
    common_config_data # Fixture from conftest.py
) -> None:
    """Test the creation of sensors and their initial state after setup via init_integration."""

    config_entry = init_integration
    mock_client_instance = mock_gemini_client_class.return_value

    # Set initial return value for get_insights for this specific test
    initial_api_response = {
        "insights": "Initial test insights",
        "alerts": "Initial test alerts",
        "summary": "Initial test summary",
    }
    mock_client_instance.get_insights.return_value = initial_api_response

    # Mock Home Assistant entities that the component will read during its first update
    hass.states.async_set("sensor.test_entity1", "123", {"friendly_name": "Test Entity 1"})

    # Apply options to the config entry. The init_integration fixture sets up the entry.
    # The options update listener in __init__.py should handle reloading the entry.
    hass.config_entries.async_update_entry(config_entry, options=COMMON_OPTIONS_DATA)
    await hass.async_block_till_done() # Allow listeners and reload to complete

    # Verify GeminiClient was instantiated correctly
    # The init_integration fixture already caused one instantiation.
    # If options update causes a reload, it might be called again.
    # We check based on the API key from common_config_data.
    mock_gemini_client_class.assert_any_call(api_key=common_config_data[CONF_API_KEY])

    # Verify get_insights was called (due to initial coordinator refresh after setup/reload)
    # The actual arguments will depend on your prompt and entity data formatting.
    # For now, let's just check it was called.
    # Call count can be tricky if reloads happen. Let's check for at least one call.
    assert mock_client_instance.get_insights.call_count >= 1


    # Check that sensors are created and have the initial state from the mock API response
    insights_sensor = hass.states.get("sensor.gemini_insights")
    alerts_sensor = hass.states.get("sensor.gemini_alerts")
    summary_sensor = hass.states.get("sensor.gemini_summary")

    assert insights_sensor is not None, "Insights sensor was not created"
    assert alerts_sensor is not None, "Alerts sensor was not created"
    assert summary_sensor is not None, "Summary sensor was not created"

    assert insights_sensor.state == initial_api_response["insights"]
    assert alerts_sensor.state == initial_api_response["alerts"]
    assert summary_sensor.state == initial_api_response["summary"]

    assert insights_sensor.attributes.get("raw_data") == initial_api_response


async def test_sensor_update_reflects_new_api_data(
    hass: HomeAssistant,
    init_integration,
    mock_gemini_client_class,
    common_config_data
) -> None:
    """Test sensor updates when coordinator data changes due to new API data."""
    config_entry = init_integration
    mock_client_instance = mock_gemini_client_class.return_value

    hass.states.async_set("sensor.test_entity1", "123") # Initial entity state

    # Apply options
    hass.config_entries.async_update_entry(config_entry, options=COMMON_OPTIONS_DATA)
    await hass.async_block_till_done()

    # Initial call happened during setup/reload from options update.
    # Let's clear mocks or track call count carefully if needed.
    # For simplicity, we'll focus on the change after a manual refresh.

    # Find the coordinator instance
    # This is a common way to get the coordinator in tests.
    coordinator: DataUpdateCoordinator = None
    for coord_obj in hass.data.get("update_coordinator", {}).values():
        if coord_obj.name == "gemini_insights_sensor": # Name given in sensor.py
            coordinator = coord_obj
            break
    assert coordinator is not None, "DataUpdateCoordinator not found"

    # Change the mock return value for the next API call
    updated_api_response = {
        "insights": "Updated insights from API",
        "alerts": "Updated alerts from API",
        "summary": "Updated summary from API",
    }
    mock_client_instance.get_insights.return_value = updated_api_response

    # Manually trigger an update of the coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done() # Wait for listeners to process the update

    insights_sensor = hass.states.get("sensor.gemini_insights")
    alerts_sensor = hass.states.get("sensor.gemini_alerts")
    summary_sensor = hass.states.get("sensor.gemini_summary")

    assert insights_sensor.state == updated_api_response["insights"]
    assert alerts_sensor.state == updated_api_response["alerts"]
    assert summary_sensor.state == updated_api_response["summary"]
    assert insights_sensor.attributes.get("raw_data") == updated_api_response


async def test_sensor_handles_api_error_gracefully(
    hass: HomeAssistant,
    init_integration,
    mock_gemini_client_class,
    common_config_data
) -> None:
    """Test sensor behavior when the Gemini API client returns None (simulating an error)."""
    config_entry = init_integration
    mock_client_instance = mock_gemini_client_class.return_value

    hass.states.async_set("sensor.test_entity1", "456")
    hass.config_entries.async_update_entry(config_entry, options=COMMON_OPTIONS_DATA)
    await hass.async_block_till_done()

    # Configure the mock to simulate an API error by returning None
    mock_client_instance.get_insights.return_value = None

    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config_entry.entry_id].get("coordinator")
    # A more robust way to get coordinator:
    if not coordinator: # Fallback if not stored directly (though it should be based on plan)
        for coord_obj in hass.data.get("update_coordinator", {}).values():
            if coord_obj.name == "gemini_insights_sensor":
                coordinator = coord_obj
                break
    assert coordinator is not None, "DataUpdateCoordinator not found"

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    insights_sensor = hass.states.get("sensor.gemini_insights")
    alerts_sensor = hass.states.get("sensor.gemini_alerts")
    summary_sensor = hass.states.get("sensor.gemini_summary")

    # Check state based on sensor.py's error handling for None response
    assert insights_sensor.state == "Error fetching insights"
    assert alerts_sensor.state == "Error"
    assert summary_sensor.state == "Error"

    # Simulate a more specific exception from the client's get_insights call
    mock_client_instance.get_insights.side_effect = Exception("Simulated API connection problem")

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    insights_sensor = hass.states.get("sensor.gemini_insights")
    assert "Exception: Simulated API connection problem" in insights_sensor.state


async def test_sensor_when_no_entities_configured(
    hass: HomeAssistant,
    init_integration,
    mock_gemini_client_class,
    common_config_data
) -> None:
    """Test behavior when no entities are configured in options."""
    config_entry = init_integration
    mock_client_instance = mock_gemini_client_class.return_value

    # Configure with an empty entity list in options
    no_entities_options = COMMON_OPTIONS_DATA.copy()
    no_entities_options[CONF_ENTITIES] = []

    hass.config_entries.async_update_entry(config_entry, options=no_entities_options)
    await hass.async_block_till_done() # This should trigger a reload and re-setup

    insights_sensor = hass.states.get("sensor.gemini_insights")
    assert insights_sensor is not None
    # Check state based on sensor.py's handling of no entities
    assert insights_sensor.state == "No entities configured."

    # Gemini client's get_insights should not have been called if no entities are configured
    # The call count might be >0 if previous tests or initial setup (before options) called it.
    # For this specific scenario (no entities), after options update and reload, it should not be called.
    # To be precise, we might need to reset the mock or check calls *after* the options update.
    # For simplicity, if it was called during initial setup before options, that's one thing.
    # The key is that during an update cycle *with no entities*, it shouldn't call.

    # Let's get the coordinator and trigger a refresh to be sure.
    coordinator: DataUpdateCoordinator = None
    for coord_obj in hass.data.get("update_coordinator", {}).values():
        if coord_obj.name == "gemini_insights_sensor":
            coordinator = coord_obj
            break
    assert coordinator is not None

    # Reset mock call count before the refresh we care about for this test condition
    mock_client_instance.get_insights.reset_mock()

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    mock_client_instance.get_insights.assert_not_called()
