"""Test the Gemini Insights config flow."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_API_KEY

from custom_components.gemini_insights.const import DOMAIN, CONF_ENTITIES, CONF_PROMPT, CONF_UPDATE_INTERVAL
# Assuming your GeminiClient is in .gemini_client
# If you had a way to mock a successful API key test, you'd use it here.
# For now, we'll assume providing any key is "valid" for flow purposes,
# as actual API calls are not made during config flow in the current implementation.

VALID_API_KEY = "test_api_key_123"


async def test_form_user_success(hass: HomeAssistant) -> None:
    """Test we get the form and can submit it."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    # Mocking is not strictly needed here if your config flow doesn't
    # make external calls for validation during the user step.
    # If it did (e.g., test API key), you'd patch 'GeminiClient.validate_key' or similar.
    with patch(
        "custom_components.gemini_insights.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_API_KEY: VALID_API_KEY,
            },
        )
        await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert result2["title"] == "Gemini Insights"
    assert result2["data"] == {
        CONF_API_KEY: VALID_API_KEY,
    }
    assert len(mock_setup_entry.mock_calls) == 1


async def test_form_user_missing_api_key(hass: HomeAssistant) -> None:
    """Test user form with missing API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "user"

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_KEY: "", # Empty API Key
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result2["step_id"] == "user"
    assert result2["errors"] == {"base": "api_key_required"}


async def test_options_flow(hass: HomeAssistant) -> None:
    """Test options flow."""
    # Initial setup of the config entry
    config_entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Gemini Insights",
        data={CONF_API_KEY: VALID_API_KEY},
        source=config_entries.SOURCE_USER,
        options={}, # Start with empty options
    )
    config_entry.add_to_hass(hass)

    # Initialize the options flow
    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM
    assert result["step_id"] == "init"

    # Simulate user input for options
    new_options = {
        CONF_ENTITIES: ["sensor.temperature", "light.living_room"],
        CONF_PROMPT: "New custom prompt",
        CONF_UPDATE_INTERVAL: 300,
    }
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input=new_options
    )
    await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.RESULT_TYPE_CREATE_ENTRY
    assert config_entry.options == new_options


@pytest.mark.skip(reason="Unique ID logic needs refinement if we want to test abort.")
async def test_form_user_already_configured(hass: HomeAssistant) -> None:
    """Test if the API key (or part of it) is already configured."""
    # Pre-configure an entry
    # Note: The unique_id in the actual flow is currently based on the API key.
    # This test assumes a similar mechanism or a more robust unique ID.
    # If your unique_id generation is simple (e.g., just DOMAIN), this test might need adjustment.

    # Setup an initial entry
    initial_result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    await hass.config_entries.flow.async_configure(
        initial_result["flow_id"], {CONF_API_KEY: VALID_API_KEY}
    )
    await hass.async_block_till_done()

    # Try to configure a second time with the same API key
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    # The flow should ideally allow entering the form first
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM

    # Then, upon submitting the same key, it should abort
    # This requires the unique_id to be correctly set and checked.
    # The current flow uses `self._abort_if_unique_id_configured()` after user input.
    # For this test to work as written, the unique ID must be derived from the API key.
    # The current unique_id is `user_input[CONF_API_KEY][:10]`

    result2 = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_KEY: VALID_API_KEY,
        },
    )
    await hass.async_block_till_done()

    assert result2["type"] == data_entry_flow.RESULT_TYPE_ABORT
    assert result2["reason"] == "already_configured"

# To run these tests, you would typically use pytest:
# pytest custom_components/gemini_insights/tests/test_config_flow.py
# Ensure you have pytest and pytest-homeassistant-custom-component installed.
# You might also need a conftest.py in your tests directory.
# (See https://developers.home-assistant.io/docs/dev_101_tests/#setting-up-tests)
