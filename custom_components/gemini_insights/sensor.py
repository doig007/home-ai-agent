"""Sensor platform for Gemini Insights."""
import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    CONF_ENTITIES,
    CONF_PROMPT,
    CONF_UPDATE_INTERVAL,
    DEFAULT_PROMPT,
    DEFAULT_UPDATE_INTERVAL,
    CONF_API_KEY,  # Added import
)
from .gemini_client import GeminiClient

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    # Access merged config and options from hass.data, prepared by __init__.py
    # This ensures that options are immediately available and used after changes.
    domain_data = hass.data[DOMAIN][entry.entry_id]
    config = domain_data["config"] # Initial setup data
    options = domain_data["options"] # Runtime options, takes precedence

    api_key = config.get(CONF_API_KEY)

    if not api_key:
        _LOGGER.error("Gemini API key not found in configuration. Component will not be set up.")
        # Consider raising ConfigEntryNotReady if you want Home Assistant to retry setup
        # from homeassistant.exceptions import ConfigEntryNotReady
        # raise ConfigEntryNotReady("API Key not available")
        return

    try:
        gemini_client = GeminiClient(api_key=api_key)
    except ValueError as e:
        _LOGGER.error(f"Failed to initialize Gemini Client: {e}")
        # This typically means an invalid API key was passed to the client's constructor.
        # Depending on HASS version, raising ConfigEntryAuthFailed might be appropriate
        # from homeassistant.exceptions import ConfigEntryAuthFailed
        # raise ConfigEntryAuthFailed("Invalid API Key for Gemini Client")
        return # Stop setup if client can't be initialized

    # Use options first, then config (for initial setup before options are saved), then default.
    update_interval_seconds = options.get(CONF_UPDATE_INTERVAL, config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL))

    async def async_update_data():
        """Fetch data from Home Assistant, send to Gemini, and return insights."""
        _LOGGER.debug("Coordinator update called")

        # Prioritize options, then config, then empty list/default prompt
        entity_ids = options.get(CONF_ENTITIES, config.get(CONF_ENTITIES, []))
        prompt_template = options.get(CONF_PROMPT, config.get(CONF_PROMPT, DEFAULT_PROMPT))

        if not entity_ids:
            _LOGGER.info("No entities configured for Gemini Insights. Skipping API call.")
            return {"insights": "No entities configured.", "alerts": "", "summary": ""}

        entity_data_map = {}
        for entity_id in entity_ids:
            state = hass.states.get(entity_id)
            if state:
                entity_data_map[entity_id] = {
                    "state": state.state,
                    "attributes": dict(state.attributes),
                    "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                    "last_updated": state.last_updated.isoformat() if state.last_updated else None,
                }
            else:
                entity_data_map[entity_id] = None
                _LOGGER.warning(f"Entity {entity_id} not found.")

        import json # Make sure json is imported
        entity_data_json = json.dumps(entity_data_map, indent=2)

        try:
            # The GeminiClient's get_insights method is synchronous.
            # The DataUpdateCoordinator will run this in an executor thread.
            insights = await hass.async_add_executor_job(
                gemini_client.get_insights, prompt_template, entity_data_json
            )
            if insights:
                _LOGGER.debug(f"Received insights from Gemini: {insights}")
                return insights
            else:
                _LOGGER.error("Failed to get insights from Gemini.")
                return {"insights": "Error fetching insights", "alerts": "Error", "summary": "Error"}
        except Exception as e:
            _LOGGER.error(f"Exception during Gemini API call in coordinator: {e}")
            return {"insights": f"Exception: {e}", "alerts": "Exception", "summary": "Exception"}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="gemini_insights_sensor",
        update_method=async_update_data,
        update_interval=timedelta(seconds=update_interval_seconds),
    )

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()

    # Create sensor entities
    sensors = [
        GeminiInsightsSensor(coordinator, "Insights"),
        GeminiInsightsSensor(coordinator, "Alerts"),
        GeminiInsightsSensor(coordinator, "Summary"),
    ]
    async_add_entities(sensors)


class GeminiInsightsSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Gemini Insights Sensor."""

    def __init__(self, coordinator: DataUpdateCoordinator, insight_type: str):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._insight_type = insight_type.lower()
        self._attr_name = f"Gemini {insight_type}"
        # Unique ID should be based on the config entry and the insight type
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{self._insight_type}"
        self._attr_icon = "mdi:brain" # Generic icon, can be changed

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            # This can happen before the first successful update or if an update fails and returns None
            _LOGGER.debug(f"Coordinator data is None for {self.name}, returning Initializing...")
            return "Initializing..."

        # Check if coordinator.data has a 'get' method (is dict-like)
        if hasattr(self.coordinator.data, 'get') and callable(self.coordinator.data.get):
            return self.coordinator.data.get(self._insight_type, "Not available")
        else:
            # This is the problematic case where data is not a dict (e.g., a coroutine or other unexpected type)
            _LOGGER.warning(
                f"Coordinator data for sensor {self.name} is not a dictionary (type: {type(self.coordinator.data)}). "
                f"This might indicate an issue with the DataUpdateCoordinator or the update_method. "
                f"Current coordinator data (snippet): {str(self.coordinator.data)[:200]}"
            )
            return "Error: Invalid data" # Or some other error indicator for the sensor state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        if self.coordinator.data:
            return {
                "last_synced": self.coordinator.last_update_success_time,
                "raw_data": self.coordinator.data # For debugging or more detailed display
            }
        return {}

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
