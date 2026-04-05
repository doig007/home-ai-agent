"""The Gemini Insights integration."""
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import CONF_API_KEY
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONFIRMATION_CONFIRMED,
    CONFIRMATION_REJECTED,
    CONF_MODEL,
    DEFAULT_MODEL,
    DOMAIN,
    MOBILE_APP_NOTIFICATION_ACTION_EVENT,
    SERVICE_RECORD_CONFIRMATION,
)

from .gemini_client import GeminiClient
from .learning import HouseholdLearningManager, parse_confirmation_action

_LOGGER = logging.getLogger(__name__)

# List of platforms that this integration will support.
PLATFORMS = ["sensor"]  # Example: if you're creating sensor entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gemini Insights from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # validate the key early
    try:
        client = await GeminiClient.async_create(
            hass,
            entry.data[CONF_API_KEY],
            entry.options.get(CONF_MODEL, entry.data.get(CONF_MODEL, DEFAULT_MODEL)),
        )
    except Exception as exc:
        raise ConfigEntryNotReady(str(exc)) from exc

    learning_manager = HouseholdLearningManager(hass, entry.entry_id)
    await learning_manager.async_load()
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "client": client,
        "learning_manager": learning_manager,
    }

    await _async_ensure_feedback_handlers(hass)

    # Add an options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options_listener))

    # Forward the setup to platforms.
    # This will allow us to create sensor entities to display the insights.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not any(
            isinstance(value, dict) and "entry" in value
            for value in hass.data[DOMAIN].values()
        ):
            unsub = hass.data[DOMAIN].pop("mobile_action_unsub", None)
            if unsub is not None:
                unsub()
            if hass.services.has_service(DOMAIN, SERVICE_RECORD_CONFIRMATION):
                hass.services.async_remove(DOMAIN, SERVICE_RECORD_CONFIRMATION)
    return unload_ok


async def async_update_options_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug(f"Options updated: {entry.options}")
    # Store the updated options in hass.data
    if DOMAIN in hass.data and entry.entry_id in hass.data[DOMAIN]:
        hass.data[DOMAIN][entry.entry_id]["options"] = dict(entry.options)
    else:
        # This case should ideally not happen if setup was successful
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = {
            "config": dict(entry.data), # Should already be there
            "options": dict(entry.options),
        }
    # Reload the entry to apply changes. This will re-setup the component.
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry."""
    _LOGGER.info(f"Removing Gemini Insights component for entry {entry.entry_id}")
    # Additional cleanup specific to the component can be done here if necessary.
    # For example, if the component created timers or other resources not tied
    # to entities, they should be cleaned up here.


async def _async_ensure_feedback_handlers(hass: HomeAssistant) -> None:
    """Ensure notification feedback listeners and services are registered once."""
    if "mobile_action_unsub" not in hass.data[DOMAIN]:
        @callback
        def _async_handle_mobile_action(event) -> None:
            """Record confirmation feedback from Home Assistant mobile notifications."""
            parsed = parse_confirmation_action(event.data.get("action"))
            if parsed is None:
                return

            entry_id, tag, outcome = parsed
            manager = hass.data.get(DOMAIN, {}).get(entry_id, {}).get("learning_manager")
            if manager is None:
                return

            hass.async_create_task(
                manager.async_record_confirmation(
                    tag,
                    outcome,
                    MOBILE_APP_NOTIFICATION_ACTION_EVENT,
                    event.data.get("reply_text"),
                )
            )

        hass.data[DOMAIN]["mobile_action_unsub"] = hass.bus.async_listen(
            MOBILE_APP_NOTIFICATION_ACTION_EVENT,
            _async_handle_mobile_action,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_RECORD_CONFIRMATION):
        async def _async_handle_record_confirmation_service(call: ServiceCall) -> None:
            """Record confirmation feedback via an explicit service call."""
            entry_id = call.data["entry_id"]
            manager = hass.data.get(DOMAIN, {}).get(entry_id, {}).get("learning_manager")
            if manager is None:
                _LOGGER.warning(
                    "Ignoring confirmation for unknown Gemini Insights entry %s",
                    entry_id,
                )
                return

            await manager.async_record_confirmation(
                call.data["tag"],
                call.data["outcome"],
                SERVICE_RECORD_CONFIRMATION,
                call.data.get("notes"),
            )

        hass.services.async_register(
            DOMAIN,
            SERVICE_RECORD_CONFIRMATION,
            _async_handle_record_confirmation_service,
            schema=vol.Schema(
                {
                    vol.Required("entry_id"): str,
                    vol.Required("tag"): str,
                    vol.Required("outcome"): vol.In(
                        [CONFIRMATION_CONFIRMED, CONFIRMATION_REJECTED]
                    ),
                    vol.Optional("notes"): str,
                }
            ),
        )
