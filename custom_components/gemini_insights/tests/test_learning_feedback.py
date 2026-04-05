"""Tests for learning, forecasting, and confirmation feedback."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.gemini_insights.const import (
    CONF_ENABLE_CONFIRMATION_NOTIFICATIONS,
    CONF_NOTIFICATION_SERVICE,
    CONFIRMATION_CONFIRMED,
    DOMAIN,
    MOBILE_APP_NOTIFICATION_ACTION_EVENT,
)


def _mock_response() -> dict:
    """Return a representative Gemini payload for learning tests."""
    pattern = "Kitchen motion around 18:00 usually means someone is cooking dinner."
    return {
        "insights": "Kitchen activity is clustering in the early evening.",
        "alerts": "",
        "forecast": "Expect another kitchen occupancy spike around dinner time.",
        "to_execute": [],
        "learning_updates": [
            {
                "pattern": pattern,
                "status": "inferred",
                "confidence": 0.82,
                "evidence": "Recent evening motion spikes appear repeatedly.",
                "entities": ["binary_sensor.kitchen_motion"],
            }
        ],
        "confirmation_requests": [
            {
                "question": "Are you usually cooking dinner when kitchen motion rises around 18:00?",
                "pattern": pattern,
                "reason": "Confirming this would improve occupancy forecasts.",
                "confidence": 0.86,
                "entities": ["binary_sensor.kitchen_motion"],
            }
        ],
        "raw_text": '{"ok": true}',
    }


async def test_setup_exposes_forecast_and_learning_profile(
    hass: HomeAssistant,
    config_entry,
    mock_gemini_client,
) -> None:
    """Setting up the integration should create forecast output and stored learning."""
    mock_gemini_client.get_insights.return_value = _mock_response()
    hass.states.async_set("binary_sensor.kitchen_motion", "on")

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    forecast_sensor = hass.states.get("sensor.gemini_forecast")
    assert forecast_sensor is not None
    assert (
        forecast_sensor.attributes["forecast"]
        == "Expect another kitchen occupancy spike around dinner time."
    )

    insights_sensor = hass.states.get("sensor.gemini_insights")
    assert insights_sensor is not None
    learning_profile = insights_sensor.attributes["learning_profile"]
    assert learning_profile["patterns"][0]["pattern"].startswith("Kitchen motion")
    assert learning_profile["pending_confirmations"][0]["question"].startswith(
        "Are you usually cooking dinner"
    )


async def test_notification_action_records_confirmation_feedback(
    hass: HomeAssistant,
    config_entry,
    mock_gemini_client,
) -> None:
    """A notification action should move a pending confirmation into stored history."""
    mock_gemini_client.get_insights.return_value = _mock_response()
    hass.states.async_set("binary_sensor.kitchen_motion", "on")

    notify_calls: list[dict] = []

    async def _handle_notify(call) -> None:
        notify_calls.append(call.data)

    hass.services.async_register("notify", "family_phone", _handle_notify)
    config_entry.options = {
        **config_entry.options,
        CONF_ENABLE_CONFIRMATION_NOTIFICATIONS: True,
        CONF_NOTIFICATION_SERVICE: "notify.family_phone",
    }

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert len(notify_calls) == 1
    confirm_action = notify_calls[0]["data"]["actions"][0]["action"]
    hass.bus.async_fire(
        MOBILE_APP_NOTIFICATION_ACTION_EVENT,
        {"action": confirm_action},
    )
    await hass.async_block_till_done()

    learning_manager = hass.data[DOMAIN][config_entry.entry_id]["learning_manager"]
    learning_profile = await learning_manager.async_get_prompt_payload()

    assert learning_profile["pending_confirmations"] == []
    assert learning_profile["recent_confirmations"][0]["outcome"] == CONFIRMATION_CONFIRMED
