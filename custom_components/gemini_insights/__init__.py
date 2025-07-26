"""The Gemini Insights integration."""
import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_API_KEY

from google import genai
from google.genai import types as t

from .const import DOMAIN

from .gemini_client import GeminiClient

_LOGGER = logging.getLogger(__name__)

# List of platforms that this integration will support.
PLATFORMS = ["sensor"]  # Example: if you're creating sensor entities


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Gemini Insights from a config entry."""
    # Store the client in hass.data so platforms can share it
    api_key = entry.data[CONF_API_KEY]

    hass.data.setdefault(DOMAIN, {})
    
    # store the entry object itself – it already has .data and .options
    hass.data[DOMAIN][entry.entry_id] = {"entry": entry}

    # Set up the coordinator
    # The coordinator will be responsible for fetching data from Home Assistant
    # and calling the Gemini API.

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
